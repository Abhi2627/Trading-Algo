# api/routes/wallet.py
import os
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.models import WalletTransaction, TransactionType
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
    amount: float


class AddFundsRequest(BaseModel):
    amount: float
    reason: str = "manual topup"


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


@router.post("/add-funds")
async def add_funds(
    request: AddFundsRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Manually add paper money to the wallet.
    Use this to simulate adding real funds for paper trading.
    """
    if request.amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be positive")
    if request.amount > 100000:
        raise HTTPException(status_code=422, detail="Cannot add more than ₹1,00,000 at once")

    wallet = await get_wallet_service().get_or_create(db)
    wallet.cash_balance = round(wallet.cash_balance + request.amount, 2)
    if wallet.total_equity > wallet.peak_equity:
        wallet.peak_equity = round(wallet.total_equity, 2)
    wallet.risk_mode = wallet.compute_risk_mode()

    db.add(WalletTransaction(
        wallet_id=wallet.id,
        type=TransactionType.topup,
        amount=request.amount,
        balance_after=wallet.cash_balance,
        description=f"Manual topup: ₹{request.amount:.0f} — {request.reason}",
    ))
    await db.commit()

    return {
        "added":        request.amount,
        "cash_balance": round(wallet.cash_balance, 2),
        "total_equity": round(wallet.total_equity, 2),
        "risk_mode":    wallet.risk_mode.value,
        "message":      f"₹{request.amount:.0f} added to wallet. New cash balance: ₹{wallet.cash_balance:.0f}"
    }


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


@router.post("/retrain")
async def trigger_retrain(
    _: str = Security(verify_key),
):
    """
    Manually trigger ML model retraining via Kaggle.
    Runs asynchronously — check Celery logs for progress.
    """
    from workers.tasks.retrain_tasks import retrain_models
    task = retrain_models.delay()
    return {"queued": True, "task_id": task.id, "message": "Retraining queued — check logs for progress (up to 2 hrs)"}


@router.get("/analytics")
async def get_analytics(
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Signal performance analytics derived from closed signal_outcome rows.
    Powers the Analytics page in the Tauri desktop app.
    """
    from sqlalchemy import select, func
    from core.models import SignalOutcome, OutcomeResult

    # All closed outcomes
    result = await db.execute(
        select(SignalOutcome).where(
            SignalOutcome.outcome != OutcomeResult.pending
        ).order_by(SignalOutcome.closed_at)
    )
    outcomes = result.scalars().all()

    if not outcomes:
        return {
            "total_trades":    0,
            "win_rate":        0.0,
            "avg_pnl_pct":     0.0,
            "avg_win_pct":     0.0,
            "avg_loss_pct":    0.0,
            "profit_factor":   0.0,
            "avg_days_held":   0.0,
            "best_trade":      None,
            "worst_trade":     None,
            "by_exit_reason":  {},
            "by_regime":       {},
            "by_confidence":   {},
            "equity_curve":    [],
        }

    wins  = [o for o in outcomes if o.outcome == OutcomeResult.correct]
    loss  = [o for o in outcomes if o.outcome == OutcomeResult.wrong]

    total_win_pct  = sum(o.pnl_pct or 0 for o in wins)
    total_loss_pct = sum(o.pnl_pct or 0 for o in loss)
    profit_factor  = (
        round(total_win_pct / abs(total_loss_pct), 2)
        if total_loss_pct < 0 else 999.0
    )

    # Best / worst trade
    sorted_by_pnl = sorted(outcomes, key=lambda o: o.pnl_pct or 0)
    worst = sorted_by_pnl[0]
    best  = sorted_by_pnl[-1]

    def outcome_dict(o: SignalOutcome) -> dict:
        return {
            "symbol":     o.symbol,
            "pnl_pct":    round((o.pnl_pct or 0) * 100, 2),
            "exit_reason": o.exit_reason,
            "days_held":   o.days_held,
            "opened_at":   o.opened_at.isoformat() if o.opened_at else None,
        }

    # By exit reason
    by_exit: dict[str, dict] = {}
    for o in outcomes:
        key = o.exit_reason or 'unknown'
        if key not in by_exit:
            by_exit[key] = {"count": 0, "wins": 0, "total_pnl_pct": 0.0}
        by_exit[key]["count"] += 1
        by_exit[key]["total_pnl_pct"] += (o.pnl_pct or 0) * 100
        if o.outcome == OutcomeResult.correct:
            by_exit[key]["wins"] += 1
    for k in by_exit:
        by_exit[k]["win_rate"] = round(
            by_exit[k]["wins"] / by_exit[k]["count"] * 100, 1
        )
        by_exit[k]["avg_pnl_pct"] = round(
            by_exit[k]["total_pnl_pct"] / by_exit[k]["count"], 2
        )

    # By market regime
    by_regime: dict[str, dict] = {}
    for o in outcomes:
        key = o.market_regime or 'unknown'
        if key not in by_regime:
            by_regime[key] = {"count": 0, "wins": 0}
        by_regime[key]["count"] += 1
        if o.outcome == OutcomeResult.correct:
            by_regime[key]["wins"] += 1
    for k in by_regime:
        by_regime[k]["win_rate"] = round(
            by_regime[k]["wins"] / by_regime[k]["count"] * 100, 1
        )

    # By confidence bucket (60-70%, 70-80%, 80-90%, 90%+)
    buckets = [(0.6, 0.7, "60-70%"), (0.7, 0.8, "70-80%"),
               (0.8, 0.9, "80-90%"), (0.9, 1.01, "90%+")]
    by_conf: dict[str, dict] = {}
    for lo, hi, label in buckets:
        subset = [o for o in outcomes if lo <= o.signal_confidence < hi]
        if not subset:
            continue
        w = sum(1 for o in subset if o.outcome == OutcomeResult.correct)
        by_conf[label] = {
            "count":    len(subset),
            "win_rate": round(w / len(subset) * 100, 1),
            "avg_pnl_pct": round(
                sum((o.pnl_pct or 0) * 100 for o in subset) / len(subset), 2
            ),
        }

    # Equity curve — cumulative realized PnL over time
    equity_curve = []
    cumulative = 0.0
    for o in sorted(outcomes, key=lambda x: x.closed_at or x.opened_at):
        cumulative += o.realized_pnl or 0
        equity_curve.append({
            "date":       (o.closed_at or o.opened_at).strftime("%Y-%m-%d"),
            "cumulative_pnl": round(cumulative, 2),
            "symbol":     o.symbol,
            "pnl":        round((o.realized_pnl or 0), 2),
        })

    total = len(outcomes)
    win_count = len(wins)

    return {
        "total_trades":  total,
        "win_count":     win_count,
        "loss_count":    len(loss),
        "win_rate":      round(win_count / total * 100, 1),
        "avg_pnl_pct":   round(sum((o.pnl_pct or 0) * 100 for o in outcomes) / total, 2),
        "avg_win_pct":   round(total_win_pct * 100  / len(wins),  2) if wins  else 0.0,
        "avg_loss_pct":  round(total_loss_pct * 100 / len(loss), 2) if loss  else 0.0,
        "profit_factor": profit_factor,
        "avg_days_held": round(sum(o.days_held or 0 for o in outcomes) / total, 1),
        "best_trade":    outcome_dict(best),
        "worst_trade":   outcome_dict(worst),
        "by_exit_reason": by_exit,
        "by_regime":      by_regime,
        "by_confidence":  by_conf,
        "equity_curve":   equity_curve,
    }
