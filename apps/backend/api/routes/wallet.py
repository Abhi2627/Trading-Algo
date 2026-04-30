# api/routes/wallet.py
import os
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.wallet.wallet_service import get_wallet_service

router = APIRouter(prefix="/wallet", tags=["wallet"])
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def verify_key(key: str = Security(api_key_header)):
    if key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


class OpenTradeRequest(BaseModel):
    signal_id:   str
    asset_symbol: str
    is_intraday: bool = False


class CloseTradeRequest(BaseModel):
    trade_id: str
    reason:   str = "manual"


class WithdrawRequest(BaseModel):
    amount: float
    reason: str = "personal withdrawal"


class SetTopupRequest(BaseModel):
    amount: float  # new monthly topup amount in INR


@router.get("/summary")
async def wallet_summary(
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Full wallet snapshot: balances, positions, drawdown, daily budget."""
    return await get_wallet_service().get_summary(db)


@router.post("/trade/open")
async def open_trade(
    request: OpenTradeRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Execute a paper BUY trade from a signal. Runs risk checks first."""
    result = await get_wallet_service().open_trade(
        db=db,
        signal_id=request.signal_id,
        asset_symbol=request.asset_symbol.upper(),
        is_intraday=request.is_intraday,
    )
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/trade/close")
async def close_trade(
    request: CloseTradeRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Close an open paper trade and realise P&L."""
    result = await get_wallet_service().close_trade(
        db=db,
        trade_id=request.trade_id,
        reason=request.reason,
    )
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/topup")
async def apply_topup(
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Manually trigger monthly top-up (normally called by Celery beat)."""
    return await get_wallet_service().apply_monthly_topup(db)


@router.post("/topup/set-amount")
async def set_topup_amount(
    request: SetTopupRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Change the monthly auto-topup amount.
    Example: if you start earning ₹2,000/month, set this to 2000.
    Takes effect from next month's 1st.
    """
    if request.amount < 0:
        raise HTTPException(status_code=422, detail="Topup amount cannot be negative")
    wallet = await get_wallet_service().get_or_create(db)
    old_amount = wallet.monthly_topup
    wallet.monthly_topup = request.amount
    await db.commit()
    return {
        "old_monthly_topup": old_amount,
        "new_monthly_topup": request.amount,
        "message": (
            f"Monthly topup updated from ₹{old_amount:.0f} to ₹{request.amount:.0f}. "
            f"Takes effect on the 1st of next month."
            if request.amount > 0
            else "Monthly auto-topup disabled. You can re-enable it anytime."
        ),
    }


@router.post("/withdraw")
async def withdraw(
    request: WithdrawRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Withdraw cash from wallet (simulate transferring to bank).
    System recalibrates capital tier and position limits automatically.
    Cannot withdraw below zero or below value of open positions.
    """
    return await get_wallet_service().withdraw(db, request.amount, request.reason)


@router.get("/capital-tier")
async def capital_tier(
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Return current capital tier and what it means for trading strategy."""
    from services.wallet.risk_manager import get_capital_tier
    wallet  = await get_wallet_service().get_or_create(db)
    summary = await get_wallet_service().get_summary(db)
    tier    = get_capital_tier(summary['total_equity'])
    return {
        "total_equity":  summary['total_equity'],
        "cash_balance":  summary['cash_balance'],
        "tier":          tier['tier'],
        "tier_label":    tier['label'],
        "description":   tier['description'],
        "max_positions": tier['max_positions'],
        "position_pct":  tier['position_pct'],
        "max_stock_price": tier['max_stock_price'],
        "etf_recommended": tier['etf_only'],
        "advice": (
            f"At ₹{summary['total_equity']:,.0f} you are in Tier {tier['tier']} ({tier['label']}). "
            f"{tier['description']}. "
            + ("Consider Nifty BeES (₹~240/unit) for affordable diversification. " if tier['etf_only'] else "")
            + f"Max position size: ₹{summary['total_equity'] * tier['position_pct']:,.0f} per trade."
        )
    }


@router.get("/history")
async def trade_history(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Return closed trades in reverse chronological order."""
    from sqlalchemy import select, desc
    from core.models import Trade, Asset, TradeStatus

    result = await db.execute(
        select(Trade, Asset)
        .join(Asset, Trade.asset_id == Asset.id)
        .where(Trade.status == TradeStatus.closed)
        .order_by(desc(Trade.exit_time))
        .limit(min(limit, 200))
    )
    rows = result.all()

    return {
        "count": len(rows),
        "trades": [
            {
                "trade_id":    str(t.id),
                "symbol":      a.symbol,
                "name":        a.name,
                "action":      t.action.value,
                "quantity":    t.quantity,
                "entry_price": t.entry_price,
                "exit_price":  t.exit_price,
                "realized_pnl":round(t.realized_pnl or 0.0, 2),
                "pnl_pct":     round(
                    ((t.exit_price - t.entry_price) / t.entry_price * 100)
                    if t.exit_price else 0.0, 2
                ),
                "trade_type":  t.trade_type.value,
                "entry_time":  t.entry_time.isoformat(),
                "exit_time":   t.exit_time.isoformat() if t.exit_time else None,
                "notes":       t.notes,
            }
            for t, a in rows
        ],
    }


@router.post("/resume")
async def resume_trading(
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Resume trading after emergency halt.
    Only works if cash balance > 0.
    """
    return await get_wallet_service().resume_trading(db)
