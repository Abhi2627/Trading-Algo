# workers/tasks/market_tasks.py
# Scheduled tasks for signal generation across all active assets.
import sys
import os
import logging

# Fix sys.path for Celery fork workers
_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from workers.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.market_tasks.scan_all_assets", bind=True, max_retries=2)
def scan_all_assets(self):
    """
    Generate signals for every active equity asset.
    Runs Mon–Fri at 8:30 AM IST.
    After scan completes, triggers auto_execute_trades.
    """
    try:
        result = run_async(_scan_all_assets_async())
        # Auto-execute trades after scan if market is open
        auto_execute_trades.delay()
        return result
    except Exception as exc:
        logger.error(f"scan_all_assets failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


async def _scan_all_assets_async() -> dict:
    import sys, os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.database import AsyncSessionLocal, init_db
    from core.models import Asset, AssetType
    from sqlalchemy import select
    from services.market_data.signal_pipeline import generate_signal
    from services.news.news_fetcher import clear_cache, fetch_global_headlines

    await init_db()
    clear_cache()
    await fetch_global_headlines()
    logger.info("News headlines pre-fetched for morning scan")

    results = {"generated": 0, "failed": 0, "skipped": 0}

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Asset)
            .where(Asset.is_active == True)  # noqa: E712
            .where(Asset.asset_type.in_([
                AssetType.equity, AssetType.crypto, AssetType.forex
            ]))
            .order_by(Asset.symbol)
        )
        assets = result.scalars().all()
        logger.info(f"Scanning {len(assets)} assets for signals")

        for asset in assets:
            try:
                signal = await generate_signal(symbol=asset.symbol, db=db)
                if signal:
                    results["generated"] += 1
                    logger.info(
                        f"{asset.symbol}: {signal['action'].upper()} "
                        f"confidence={signal['confidence']:.0%}"
                    )
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.error(f"Signal failed for {asset.symbol}: {e}")
                results["failed"] += 1
                continue

        await db.commit()

    logger.info(
        f"Scan complete: generated={results['generated']} "
        f"failed={results['failed']} skipped={results['skipped']}"
    )
    return results


@celery_app.task(name="workers.tasks.market_tasks.auto_execute_trades", bind=True, max_retries=1)
def auto_execute_trades(self):
    """
    Fully automated trade execution.
    Runs after every morning scan.
    No human intervention needed.

    Logic:
      1. Check market is open (skip on weekends/holidays)
      2. Check wallet has cash and is not halted
      3. Find today's top BUY signals above confidence threshold
      4. For each signal, run risk checks and open trade if approved
      5. Log every decision with reason (transparency)

    This is the core of the autonomous trading system.
    """
    try:
        result = run_async(_auto_execute_async())
        return result
    except Exception as exc:
        logger.error(f"auto_execute_trades failed: {exc}")
        raise self.retry(exc=exc, countdown=120)


async def _auto_execute_async() -> dict:
    import sys, os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from datetime import datetime, timezone, timedelta, date
    from core.database import AsyncSessionLocal, init_db
    from core.models import Signal, Asset, SignalAction, Trade, TradeStatus, RiskMode
    from sqlalchemy import select, desc
    from services.wallet.wallet_service import get_wallet_service
    from services.wallet.risk_manager import get_capital_tier

    await init_db()

    results = {
        "executed":  [],
        "skipped":   [],
        "rejected":  [],
        "reason":    "",
    }

    # --- 1. Market hours check (IST) ---
    ist_now  = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    weekday  = ist_now.weekday()  # 0=Mon, 6=Sun
    NSE_HOLIDAYS = {
        "2025-10-02", "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
        "2026-01-26", "2026-03-19", "2026-04-02", "2026-04-03",
        "2026-04-14", "2026-04-17", "2026-05-01", "2026-06-11",
        "2026-08-15", "2026-10-02", "2026-10-20", "2026-12-25",
    }

    if weekday >= 5:
        results["reason"] = f"Weekend ({ist_now.strftime('%A')}) — no trading"
        logger.info(results["reason"])
        return results

    if ist_now.date().isoformat() in NSE_HOLIDAYS:
        results["reason"] = f"NSE Holiday {ist_now.date()} — no trading"
        logger.info(results["reason"])
        return results

    market_open  = ist_now.replace(hour=9,  minute=15, second=0)
    market_close = ist_now.replace(hour=15, minute=30, second=0)
    if not (market_open <= ist_now <= market_close):
        results["reason"] = f"Market closed at {ist_now.strftime('%H:%M')} IST"
        logger.info(results["reason"])
        return results

    async with AsyncSessionLocal() as db:
        wallet_svc = get_wallet_service()

        # --- 2. Wallet safety checks ---
        wallet = await wallet_svc.get_or_create(db)

        if wallet.risk_mode == RiskMode.halted:
            results["reason"] = "Trading halted — wallet empty or risk limit hit"
            logger.warning(results["reason"])
            return results

        if wallet.cash_balance < 100:  # Less than ₹100 cash
            results["reason"] = f"Insufficient cash \u20b9{wallet.cash_balance:.0f} — need at least \u20b9100"
            logger.warning(results["reason"])
            return results

        tier = get_capital_tier(wallet.total_equity)
        logger.info(
            f"Auto-execute: cash=\u20b9{wallet.cash_balance:.0f} "
            f"equity=\u20b9{wallet.total_equity:.0f} "
            f"tier={tier['tier']} ({tier['label']})"
        )

        # --- 3. Count existing open positions ---
        open_positions_result = await db.execute(
            select(Trade).where(Trade.status == TradeStatus.open)
        )
        current_open = len(open_positions_result.scalars().all())
        max_allowed  = tier["max_positions"]

        if current_open >= max_allowed:
            results["reason"] = (
                f"Max positions reached ({current_open}/{max_allowed}) "
                f"for Tier {tier['tier']}"
            )
            logger.info(results["reason"])
            return results

        slots_available = max_allowed - current_open
        logger.info(f"Open positions: {current_open}/{max_allowed} — {slots_available} slot(s) available")

        # --- 4. Get today's top BUY signals ---
        today_start = datetime.combine(
            date.today(), datetime.min.time()
        ).replace(tzinfo=timezone.utc)

        # Confidence threshold per tier:
        # Tier 1/2 (small capital): 65% — need more opportunities
        # Tier 3/4 (larger capital): 60% — can afford to be less strict
        # Stop-loss + trailing stop protect downside regardless
        min_confidence = 0.65 if tier["tier"] <= 2 else 0.60

        signals_result = await db.execute(
            select(Signal, Asset)
            .join(Asset, Signal.asset_id == Asset.id)
            .where(Signal.created_at >= today_start)
            .where(Signal.confidence >= min_confidence)
            .where(Signal.action == SignalAction.buy)
            .order_by(desc(Signal.ensemble_score))
            .limit(20)  # top 20, will filter to slots_available
        )
        top_signals = signals_result.all()

        # Deduplicate signals: same symbol, keep highest confidence only
        # Also prefer NSE over BSE
        seen_tickers: dict = {}  # ticker -> (signal, asset)
        for s, a in top_signals:
            ticker = a.symbol.split(":")[-1]
            exchange = a.symbol.split(":")[0]
            if ticker not in seen_tickers:
                seen_tickers[ticker] = (s, a)
            else:
                existing_s, existing_a = seen_tickers[ticker]
                existing_exchange = existing_a.symbol.split(":")[0]
                # Prefer NSE over BSE, then higher confidence
                if exchange == "NSE" and existing_exchange != "NSE":
                    seen_tickers[ticker] = (s, a)
                elif exchange == existing_exchange and s.confidence > existing_s.confidence:
                    seen_tickers[ticker] = (s, a)

        unique_signals = list(seen_tickers.values())

        logger.info(
            f"Found {len(unique_signals)} unique BUY signals ≥{min_confidence:.0%} confidence"
        )

        if not unique_signals:
            results["reason"] = f"No signals met the {min_confidence:.0%} confidence threshold"
            logger.info(results["reason"])
            return results

        # --- 5. Execute trades for top signals (fill ALL available slots) ---
        trades_opened = 0
        cash_exhausted = False

        # Fetch 2x signal pool so individual rejections don't block remaining slots.
        # e.g. Tier 2 has 3 slots: if signal #1 is rejected for price, we still try #2 and #3.
        for signal, asset in unique_signals[: slots_available * 2]:
            if trades_opened >= slots_available:
                break
            if cash_exhausted:
                break
            if wallet.cash_balance < 100:
                logger.info(f"Cash exhausted (₹{wallet.cash_balance:.0f}) — stopping")
                break

            logger.info(
                f"Attempting auto-trade [{trades_opened + 1}/{slots_available}]: {asset.symbol} "
                f"conf={signal.confidence:.0%} "
                f"score={signal.ensemble_score:.3f}"
            )

            result = await wallet_svc.open_trade(
                db=db,
                signal_id=str(signal.id),
                asset_symbol=asset.symbol,
                is_intraday=False,  # always positional for small capital
            )

            if result.get("approved"):
                trades_opened += 1
                results["executed"].append({
                    "symbol":        asset.symbol,
                    "quantity":      result["quantity"],
                    "entry_price":   result["entry_price"],
                    "position_size": result["position_size"],
                    "stop_loss":     result["stop_loss"],
                    "take_profit":   result["take_profit"],
                    "confidence":    round(signal.confidence * 100, 1),
                })
                logger.info(
                    f"AUTO-TRADE OPENED [{trades_opened}/{slots_available}]: {asset.symbol} "
                    f"qty={result['quantity']} "
                    f"@ \u20b9{result['entry_price']:.2f} "
                    f"| SL \u20b9{result['stop_loss']} "
                    f"| TP \u20b9{result['take_profit']} "
                    f"| cash left \u20b9{result['cash_remaining']:.2f}"
                )
            else:
                reason = result.get("reason", "unknown")
                results["rejected"].append({
                    "symbol": asset.symbol,
                    "reason": reason,
                })
                logger.info(f"Auto-trade rejected for {asset.symbol}: {reason}")

                # Only truly stop when cash is gone — price/tier rejections
                # should NOT block the remaining open slot attempts.
                if "cash" in reason.lower() and "insufficient" in reason.lower():
                    logger.info("Stopping — insufficient cash for any more trades")
                    cash_exhausted = True

        await db.commit()

    results["reason"] = (
        f"Executed {len(results['executed'])} trade(s), "
        f"rejected {len(results['rejected'])}"
    )
    logger.info(f"Auto-execute complete: {results['reason']}")
    return results


@celery_app.task(name="workers.tasks.market_tasks.generate_signal_for_symbol")
def generate_signal_for_symbol(symbol: str, headlines: list = None):
    """
    On-demand signal generation for a single symbol.
    Can be triggered manually from the API or chatbot.
    """
    return run_async(_generate_single(symbol, headlines or []))


async def _generate_single(symbol: str, headlines: list) -> dict:
    import sys, os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.database import AsyncSessionLocal
    from services.market_data.signal_pipeline import generate_signal

    async with AsyncSessionLocal() as db:
        result = await generate_signal(symbol=symbol, db=db, headlines=headlines)
        if result:
            await db.commit()
        return result or {"error": f"Signal generation failed for {symbol}"}

