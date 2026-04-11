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
