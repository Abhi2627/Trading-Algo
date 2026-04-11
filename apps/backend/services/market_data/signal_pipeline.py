# services/market_data/signal_pipeline.py
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.models import Asset, Signal, SignalAction
from services.market_data.fetcher import fetch_historical
from services.market_data.features import get_latest_features, detect_market_regime, compute_features
from models.rl.agent import get_rl_agent
from models.transformer.forecaster import get_forecaster
from models.sentiment.sentiment_service import get_sentiment_service
from models.ensemble.ensemble import get_ensemble_engine

logger = logging.getLogger(__name__)


async def generate_signal(
    symbol: str,
    db: AsyncSession,
    headlines: list[str] = None,
    portfolio_state: dict = None,
) -> Optional[dict]:
    """
    Full signal pipeline for one symbol.
    Fetch -> Features -> Models -> Ensemble -> Persist.
    Returns the signal dict or None on failure.
    """
    # 1. Resolve asset
    result = await db.execute(select(Asset).where(Asset.symbol == symbol))
    asset = result.scalar_one_or_none()
    if asset is None:
        logger.error(f"Asset not found: {symbol}")
        return None

    # 2. Fetch OHLCV (365 days for features, need 60+ rows minimum)
    df = fetch_historical(symbol, period_days=365, interval="1d")
    if df is None or len(df) < 60:
        logger.error(f"Insufficient data for {symbol}")
        return None

    # 3. Compute features
    features_df = compute_features(df)
    if features_df is None:
        logger.error(f"Feature computation failed for {symbol}")
        return None

    latest_features = features_df.iloc[-1].to_dict()
    regime = detect_market_regime(df)

    # Build feature history list for Transformer (needs SEQ_LEN=60 dicts)
    features_history = [row.to_dict() for _, row in features_df.tail(60).iterrows()]

    # 4. Run models in parallel conceptually; sequential here for simplicity
    rl_agent   = get_rl_agent()
    forecaster = get_forecaster()
    sentiment  = get_sentiment_service()
    ensemble   = get_ensemble_engine()

    rl_output          = rl_agent.predict(latest_features, portfolio_state or {})
    transformer_output = forecaster.predict(features_history)
    sentiment_output   = await sentiment.analyse(headlines or [], symbol=symbol)

    # 5. Ensemble
    result_signal = ensemble.combine(
        rl_output=rl_output,
        transformer_output=transformer_output,
        sentiment_output=sentiment_output,
        market_regime=regime,
    )
    audit = ensemble.audit_record(result_signal, rl_output, transformer_output, sentiment_output)

    # 6. Persist signal
    signal = Signal(
        asset_id=asset.id,
        action=result_signal["signal_action"],
        confidence=result_signal["confidence"],
        rl_score=result_signal["rl_score"],
        transformer_score=result_signal["transformer_score"],
        sentiment_score=result_signal["sentiment_score"],
        ensemble_score=result_signal["ensemble_score"],
        market_regime=regime,
        technical_indicators={
            k: latest_features.get(k)
            for k in ["rsi_14", "macd_line", "adx", "bb_width",
                      "volume_ratio", "atr_pct", "close_vs_ema50"]
        },
        sentiment_sources=[
            {"headline": h, "source": "news"} for h in (headlines or [])
        ],
        is_intraday=False,
    )
    db.add(signal)
    await db.flush()  # get signal.id without committing

    logger.info(
        f"Signal generated: {symbol} {result_signal['action'].upper()} "
        f"confidence={result_signal['confidence']:.2f} regime={regime}"
    )

    return {
        "signal_id":  str(signal.id),
        "symbol":     symbol,
        "action":     result_signal["action"],
        "confidence": result_signal["confidence"],
        "ensemble_score": result_signal["ensemble_score"],
        "market_regime":  regime,
        "audit":          audit,
        "current_price":  float(features_df["close"].iloc[-1]),
        "generated_at":   datetime.now(timezone.utc).isoformat(),
    }


async def get_latest_signal(symbol: str, db: AsyncSession) -> Optional[Signal]:
    """Fetch the most recent signal for a symbol from DB."""
    result = await db.execute(
        select(Asset).where(Asset.symbol == symbol)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        return None

    sig_result = await db.execute(
        select(Signal)
        .where(Signal.asset_id == asset.id)
        .order_by(Signal.created_at.desc())
        .limit(1)
    )
    return sig_result.scalar_one_or_none()
