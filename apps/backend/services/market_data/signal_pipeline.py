# services/market_data/signal_pipeline.py
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.models import Asset, Signal, SignalAction, Trade, TradeStatus
from services.market_data.fetcher import fetch_historical
from services.market_data.features import get_latest_features, detect_market_regime, compute_features
from services.market_data.fundamentals import get_fscore
from services.news.news_fetcher import get_headlines_for_symbol
from models.rl.agent import get_rl_agent
from models.transformer.forecaster import get_forecaster
from models.sentiment.sentiment_service import get_sentiment_service
from models.ensemble.ensemble import get_ensemble_engine
from models.ensemble.meta_agent import get_meta_agent

logger = logging.getLogger(__name__)


async def generate_signal(
    symbol: str,
    db: AsyncSession,
    headlines: list[str] = None,
    portfolio_state: dict = None,
) -> Optional[dict]:
    """
    Full signal pipeline for one symbol.
    Fetch -> F-Score filter -> Features -> Models -> Ensemble -> Persist.
    Returns the signal dict or None on failure.
    """
    # 1. Resolve asset
    result = await db.execute(select(Asset).where(Asset.symbol == symbol))
    asset  = result.scalar_one_or_none()
    if asset is None:
        logger.error(f"Asset not found: {symbol}")
        return None

    try:
        # 2. Piotroski F-Score pre-filter
        # Run in thread executor to avoid blocking the event loop
        # (yfinance is synchronous)
        import asyncio
        loop     = asyncio.get_event_loop()
        fscore_result = await loop.run_in_executor(None, get_fscore, symbol)

        if not fscore_result['pass_filter']:
            logger.info(
                f"{symbol}: SKIPPED by F-Score filter "
                f"(score={fscore_result['fscore']}/9, grade={fscore_result['grade']})"
            )
            # Still persist a HOLD signal so the scan doesn't leave gaps
            # but mark it with very low confidence
            fscore_hold = Signal(
                asset_id  = asset.id,
                action    = SignalAction.hold,
                confidence= 0.0,
                rl_score  = 0.0,
                transformer_score = 0.0,
                sentiment_score   = 0.0,
                ensemble_score    = 0.0,
                market_regime     = 'filtered',
                technical_indicators = {},
                sentiment_sources    = [],
                is_intraday          = False,
            )
            db.add(fscore_hold)
            await db.flush()
            return {
                'signal_id':    str(fscore_hold.id),
                'symbol':       symbol,
                'action':       'hold',
                'confidence':   0.0,
                'ensemble_score': 0.0,
                'market_regime':  'filtered',
                'fscore':         fscore_result['fscore'],
                'fscore_grade':   fscore_result['grade'],
                'audit':          {},
                'current_price':  0.0,
                'generated_at':   datetime.now(timezone.utc).isoformat(),
            }

        # 3. Fetch OHLCV
        df = fetch_historical(symbol, period_days=1825, interval="1d")
        if df is None or len(df) < 60:
            logger.error(f"Insufficient data for {symbol}")
            return None

        # 4. Compute features
        features_df = compute_features(df)
        if features_df is None:
            logger.error(f"Feature computation failed for {symbol}")
            return None

        latest_features  = features_df.iloc[-1].to_dict()
        regime           = detect_market_regime(df)
        features_history = [row.to_dict() for _, row in features_df.tail(60).iterrows()]

        # 5. Run models
        rl_agent   = get_rl_agent()
        forecaster = get_forecaster()
        sentiment  = get_sentiment_service()
        ensemble   = get_ensemble_engine()
        meta_agent = get_meta_agent()

        rl_output          = rl_agent.predict(latest_features, portfolio_state or {})
        transformer_output = forecaster.predict(features_history)

        # Auto-fetch headlines if none supplied or empty
        if not headlines:
            headlines = await get_headlines_for_symbol(symbol)
            if headlines:
                logger.debug(f"{symbol}: auto-fetched {len(headlines)} headlines")

        sentiment_output = await sentiment.analyse(headlines or [], symbol=symbol)

        # 6. Meta-Agent decides weights dynamically
        meta_weights = await meta_agent.decide_weights(
            market_regime       = regime,
            rl_confidence       = rl_output.get("confidence", 0.0),
            rl_action           = rl_output.get("action", "hold"),
            transformer_conf    = transformer_output.get("confidence", 0.0),
            transformer_dir     = transformer_output.get("direction", "sideways"),
            transformer_delta   = transformer_output.get("delta_1d", 0.0),
            sentiment_score     = sentiment_output.get("score", 0.0),
            sentiment_magnitude = sentiment_output.get("magnitude", 0.0),
            sentiment_direction = sentiment_output.get("direction", "neutral"),
            news_count          = len(headlines or []),
            symbol              = symbol,
        )

        # 7. Ensemble with dynamic weights
        result_signal = ensemble.combine(
            rl_output          = rl_output,
            transformer_output = transformer_output,
            sentiment_output   = sentiment_output,
            market_regime      = regime,
            weights            = meta_weights,
        )
        audit = ensemble.audit_record(
            result_signal, rl_output, transformer_output, sentiment_output
        )

        # Add F-Score to audit
        audit['fscore']       = fscore_result['fscore']
        audit['fscore_grade'] = fscore_result['grade']

    except Exception as e:
        logger.exception(f"Signal pipeline crash for {symbol}: {e}")
        return None

    # 7. Position-aware action remapping
    open_trade_result = await db.execute(
        select(Trade)
        .where(Trade.asset_id == asset.id)
        .where(Trade.status == TradeStatus.open)
        .limit(1)
    )
    has_open_position = open_trade_result.scalar_one_or_none() is not None

    raw_action = result_signal["action"]
    if raw_action == "sell" and not has_open_position:
        result_signal["action"]        = "hold"
        result_signal["signal_action"] = SignalAction.hold
        logger.info(f"{symbol}: SELL remapped to HOLD (no open position)")
    elif raw_action == "buy" and has_open_position:
        result_signal["action"]        = "hold"
        result_signal["signal_action"] = SignalAction.hold
        logger.info(f"{symbol}: BUY remapped to HOLD (position already open)")

    # 8. Persist signal
    signal = Signal(
        asset_id          = asset.id,
        action            = result_signal["signal_action"],
        confidence        = result_signal["confidence"],
        rl_score          = result_signal["rl_score"],
        transformer_score = result_signal["transformer_score"],
        sentiment_score   = result_signal["sentiment_score"],
        ensemble_score    = result_signal["ensemble_score"],
        market_regime     = regime,
        technical_indicators = {
            k: latest_features.get(k)
            for k in ["rsi_14", "macd_line", "adx", "bb_width",
                      "volume_ratio", "atr_pct", "close_vs_ema50"]
        },
        sentiment_sources = [{"headline": h, "source": "rss"} for h in (headlines or [])],
        is_intraday       = False,
    )
    db.add(signal)
    await db.flush()

    # Create a pending PredictionOutcome row so the evening report can score it.
    # predicted_direction: up if BUY, down if SELL, sideways if HOLD
    # predicted_delta_pct: ensemble_score as a proxy for expected move magnitude
    from core.models import PredictionOutcome, OutcomeResult
    _direction_map = {'buy': 'up', 'sell': 'down', 'hold': 'sideways'}
    _predicted_dir = _direction_map.get(result_signal['action'], 'sideways')
    db.add(PredictionOutcome(
        signal_id           = signal.id,
        report_id           = None,   # linked to evening report when scored
        predicted_direction = _predicted_dir,
        predicted_delta_pct = round(result_signal['ensemble_score'] * 2, 3),  # rough estimate
        outcome             = OutcomeResult.pending,
    ))

    logger.info(
        f"Signal: {symbol} {result_signal['action'].upper()} "
        f"conf={result_signal['confidence']:.2f} "
        f"regime={regime} fscore={fscore_result['fscore']}/9"
    )

    return {
        "signal_id":      str(signal.id),
        "symbol":         symbol,
        "action":         result_signal["action"],
        "confidence":     result_signal["confidence"],
        "ensemble_score": result_signal["ensemble_score"],
        "market_regime":  regime,
        "fscore":         fscore_result["fscore"],
        "fscore_grade":   fscore_result["grade"],
        "audit":          audit,
        "current_price":  float(features_df["close"].iloc[-1]),
        "generated_at":   datetime.now(timezone.utc).isoformat(),
    }


async def get_latest_signal(symbol: str, db: AsyncSession) -> Optional[Signal]:
    """Fetch the most recent signal for a symbol from DB."""
    result = await db.execute(select(Asset).where(Asset.symbol == symbol))
    asset  = result.scalar_one_or_none()
    if asset is None:
        return None

    sig_result = await db.execute(
        select(Signal)
        .where(Signal.asset_id == asset.id)
        .order_by(Signal.created_at.desc())
        .limit(1)
    )
    return sig_result.scalar_one_or_none()

