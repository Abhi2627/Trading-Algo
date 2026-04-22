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


@router.get("/top-picks")
async def top_picks(
    limit: int = 5,
    min_confidence: float = 0.50,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Return today's highest-confidence BUY signals across all assets.
    This is the daily watchlist — sorted by ensemble score descending.
    Run POST /signals/generate/{symbol} for each asset first (or let Celery do it).
    """
    from datetime import date, datetime, timezone
    from sqlalchemy import desc
    from core.models import Signal, Asset, SignalAction

    today_start = datetime.combine(date.today(), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )

    result = await db.execute(
        select(Signal, Asset)
        .join(Asset, Signal.asset_id == Asset.id)
        .where(Signal.created_at >= today_start)
        .where(Signal.confidence >= min_confidence)
        .where(Signal.action == SignalAction.buy)
        .order_by(desc(Signal.ensemble_score))
        .limit(50)  # fetch more to allow dedup
    )
    rows = result.all()

    # Deduplicate: same stock on NSE and BSE — keep NSE, drop BSE duplicate
    seen_tickers: set[str] = set()
    deduped = []
    # First pass: NSE symbols
    for s, a in rows:
        ticker = a.symbol.split(':')[-1]
        if a.symbol.startswith('NSE:') and ticker not in seen_tickers:
            seen_tickers.add(ticker)
            deduped.append((s, a))
    # Second pass: BSE symbols not already covered by NSE
    for s, a in rows:
        ticker = a.symbol.split(':')[-1]
        if a.symbol.startswith('BSE:') and ticker not in seen_tickers:
            seen_tickers.add(ticker)
            deduped.append((s, a))

    # Sort by ensemble score and apply limit
    deduped.sort(key=lambda x: x[0].ensemble_score, reverse=True)
    deduped = deduped[:min(limit, 20)]

    return {
        "date":  date.today().isoformat(),
        "count": len(deduped),
        "picks": [
            {
                "signal_id":     str(s.id),
                "symbol":        a.symbol,
                "name":          a.name,
                "asset_type":    a.asset_type.value,
                "action":        s.action.value,
                "confidence":    round(s.confidence * 100, 1),
                "ensemble_score":round(s.ensemble_score, 4),
                "market_regime": s.market_regime,
                "rsi":           (s.technical_indicators or {}).get("rsi_14"),
                "created_at":    s.created_at.isoformat(),
            }
            for s, a in deduped
        ],
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
