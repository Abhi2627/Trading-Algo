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


# NSE holidays 2025-2026 (add more as announced)
NSE_HOLIDAYS = {
    # 2025
    "2025-01-26", "2025-02-19", "2025-03-14", "2025-03-31",
    "2025-04-10", "2025-04-14", "2025-04-18", "2025-05-01",
    "2025-08-15", "2025-08-27", "2025-10-02", "2025-10-02",
    "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
    # 2026
    "2026-01-26", "2026-03-19", "2026-04-02", "2026-04-03",
    "2026-04-14", "2026-04-17", "2026-05-01", "2026-06-11",
    "2026-08-15", "2026-10-02", "2026-10-20", "2026-12-25",
}


def is_market_open() -> dict:
    """Check if NSE is currently open."""
    from datetime import date, datetime, timezone, timedelta
    # IST = UTC+5:30
    ist_now  = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    today    = ist_now.date()
    weekday  = today.weekday()  # 0=Mon, 6=Sun
    date_str = today.isoformat()

    if weekday >= 5:  # Saturday or Sunday
        return {
            "is_open": False,
            "reason":  f"Weekend ({['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][weekday]})",
            "next_open": "Monday 9:15 AM IST",
            "market_hours": "9:15 AM - 3:30 PM IST, Mon-Fri",
        }

    if date_str in NSE_HOLIDAYS:
        return {
            "is_open": False,
            "reason":  f"NSE Holiday ({date_str})",
            "next_open": "Next trading day 9:15 AM IST",
            "market_hours": "9:15 AM - 3:30 PM IST, Mon-Fri",
        }

    market_open  = ist_now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
    pre_open     = ist_now.replace(hour=9,  minute=0,  second=0, microsecond=0)

    if ist_now < pre_open:
        return {
            "is_open": False,
            "reason":  "Pre-market (opens at 9:15 AM IST)",
            "next_open": "Today 9:15 AM IST",
            "market_hours": "9:15 AM - 3:30 PM IST, Mon-Fri",
        }
    elif ist_now > market_close:
        return {
            "is_open": False,
            "reason":  "Market closed (closed at 3:30 PM IST)",
            "next_open": "Tomorrow 9:15 AM IST" if weekday < 4 else "Monday 9:15 AM IST",
            "market_hours": "9:15 AM - 3:30 PM IST, Mon-Fri",
        }

    return {
        "is_open": True,
        "reason":  "Market open",
        "closes_at": "3:30 PM IST",
        "market_hours": "9:15 AM - 3:30 PM IST, Mon-Fri",
    }

@router.get("/market-status")
async def market_status():
    """Check if NSE is currently open for trading."""
    return is_market_open()


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

    market = is_market_open()

    return {
        "date":          date.today().isoformat(),
        "count":         len(deduped),
        "market_status": market,
        "note":          None if market["is_open"] else f"Market closed: {market['reason']}. Showing Friday's signals for reference only. No trading recommended.",
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


@router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    days: int = 90,
    _: str = Security(verify_key),
):
    """
    Return OHLCV data for candlestick chart.
    days: number of trading days to return (default 90 = ~3 months)
    """
    from services.market_data.fetcher import fetch_historical
    df = fetch_historical(symbol.upper(), period_days=days, interval="1d")
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")

    # Return last `days` rows
    df = df.tail(days)
    return {
        "symbol": symbol.upper(),
        "days":   len(df),
        "candles": [
            {
                "date":   str(idx.date()),
                "open":   round(float(row["open"]),   2),
                "high":   round(float(row["high"]),   2),
                "low":    round(float(row["low"]),    2),
                "close":  round(float(row["close"]),  2),
                "volume": int(row["volume"]),
            }
            for idx, row in df.iterrows()
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
