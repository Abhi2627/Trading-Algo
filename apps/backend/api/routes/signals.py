# api/routes/signals.py
import os
from fastapi import APIRouter, Depends, HTTPException, Security, Body
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from core.database import get_db
from core.models import Asset, Signal
from services.market_data.signal_pipeline import generate_signal, get_latest_signal

router = APIRouter(prefix="/signals", tags=["signals"])
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def verify_key(key: str = Security(api_key_header)):
    if key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


@router.post("/generate/{symbol}")
async def trigger_signal(
    symbol: str,
    headlines: list[str] = Body(default=[]),
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Trigger full signal pipeline for a symbol.
    Optionally pass news headlines for sentiment scoring.
    """
    result = await generate_signal(
        symbol=symbol.upper(),
        db=db,
        headlines=headlines,
    )
    if result is None:
        raise HTTPException(
            status_code=422,
            detail=f"Signal generation failed for '{symbol}'. Check logs."
        )
    return result


@router.get("/latest/{symbol}")
async def latest_signal(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Return the most recently generated signal for a symbol."""
    signal = await get_latest_signal(symbol.upper(), db)
    if signal is None:
        raise HTTPException(
            status_code=404,
            detail=f"No signal found for '{symbol}'. Run POST /signals/generate/{symbol} first."
        )
    return {
        "signal_id":       str(signal.id),
        "action":          signal.action.value,
        "confidence":      signal.confidence,
        "ensemble_score":  signal.ensemble_score,
        "rl_score":        signal.rl_score,
        "transformer_score": signal.transformer_score,
        "sentiment_score": signal.sentiment_score,
        "market_regime":   signal.market_regime,
        "technical_indicators": signal.technical_indicators,
        "is_intraday":     signal.is_intraday,
        "created_at":      signal.created_at.isoformat(),
    }


@router.get("/history/{symbol}")
async def signal_history(
    symbol: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Return the last N signals for a symbol."""
    asset_result = await db.execute(
        select(Asset).where(Asset.symbol == symbol.upper())
    )
    asset = asset_result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")

    signals_result = await db.execute(
        select(Signal)
        .where(Signal.asset_id == asset.id)
        .order_by(Signal.created_at.desc())
        .limit(min(limit, 100))
    )
    signals = signals_result.scalars().all()

    return {
        "symbol": symbol.upper(),
        "count":  len(signals),
        "signals": [
            {
                "signal_id":  str(s.id),
                "action":     s.action.value,
                "confidence": s.confidence,
                "ensemble_score": s.ensemble_score,
                "market_regime":  s.market_regime,
                "created_at":     s.created_at.isoformat(),
            }
            for s in signals
        ],
    }
