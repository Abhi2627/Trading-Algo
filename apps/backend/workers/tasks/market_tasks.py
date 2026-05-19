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
    Runs Mon-Fri at 8:30 AM IST.
    After scan completes, triggers auto_execute_trades.
    """
    import asyncio, threading
    result = {}
    exc_holder = [None]

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_scan_all_assets_async()))
        except Exception as e:
            exc_holder[0] = e
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()

    if exc_holder[0]:
        raise self.retry(exc=exc_holder[0], countdown=60)

    auto_execute_trades.delay()
    return result


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

        asset_symbols = [a.symbol for a in assets]

        # Run each asset in its own isolated thread with its own event loop.
        # This avoids asyncpg connection pool conflicts from shared loops.
        import asyncio
        import concurrent.futures

        def _run_single_asset(symbol: str) -> dict:
            """Run signal generation for one symbol in a completely isolated thread."""
            import asyncio as _asyncio
            result = {'symbol': symbol, 'status': 'failed'}
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                async def _inner():
                    from core.database import AsyncSessionLocal
                    from services.market_data.signal_pipeline import generate_signal
                    async with AsyncSessionLocal() as asset_db:
                        sig = await generate_signal(symbol=symbol, db=asset_db)
                        return sig
                sig = loop.run_until_complete(_inner())
                if sig:
                    result['status'] = 'generated'
                    result['signal'] = sig
                else:
                    result['status'] = 'skipped'
            except Exception as e:
                logger.error(f"Signal failed for {symbol}: {e}")
                result['error'] = str(e)
            finally:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
                _asyncio.set_event_loop(None)
            return result

        # Use ThreadPoolExecutor with max 5 workers (gentle on NSE API)
        WORKERS = 5
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(_run_single_asset, sym): sym
                       for sym in asset_symbols}
            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    if res['status'] == 'generated':
                        results['generated'] += 1
                        sig = res.get('signal', {})
                        logger.info(
                            f"Signal: {res['symbol']} "
                            f"{sig.get('action','?').upper()} "
                            f"conf={sig.get('confidence',0):.2f} "
                            f"regime={sig.get('market_regime','?')}"
                        )
                    elif res['status'] == 'skipped':
                        results['skipped'] += 1
                    else:
                        results['failed'] += 1
                except Exception as e:
                    logger.error(f"Executor error: {e}")
                    results['failed'] += 1

        logger.info(
            f"Scan complete: generated={results['generated']} "
            f"failed={results['failed']} skipped={results['skipped']}"
        )

    return results


@celery_app.task(name="workers.tasks.market_tasks.auto_execute_trades", bind=True, max_retries=1)
def auto_execute_trades(self):
    """
    Fully automated trade execution after morning scan.
    Uses portfolio engine for dynamic allocation — no hardcoded position limits.
    """
    import asyncio, threading
    result = {}
    exc_holder = [None]

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_auto_execute_async()))
        except Exception as e:
            exc_holder[0] = e
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()

    if exc_holder[0]:
        raise self.retry(exc=exc_holder[0], countdown=120)

    return result


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
    weekday  = ist_now.weekday()
    NSE_HOLIDAYS = {
        "2025-10-02", "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
        "2026-01-26", "2026-03-19", "2026-04-02", "2026-04-03",
        "2026-04-14", "2026-04-17", "2026-05-01", "2026-06-11",
        "2026-08-15", "2026-10-02", "2026-10-20", "2026-12-25",
    }

    if weekday >= 5:
        results["reason"] = f"Weekend ({ist_now.strftime('%A')}) — no trading"
        return results

    if ist_now.date().isoformat() in NSE_HOLIDAYS:
        results["reason"] = f"NSE Holiday {ist_now.date()} — no trading"
        return results

    market_open  = ist_now.replace(hour=9,  minute=15, second=0)
    market_close = ist_now.replace(hour=15, minute=30, second=0)
    if not (market_open <= ist_now <= market_close):
        results["reason"] = f"Market closed at {ist_now.strftime('%H:%M')} IST"
        return results

    async with AsyncSessionLocal() as db:
        wallet_svc = get_wallet_service()
        wallet = await wallet_svc.get_or_create(db)

        if wallet.risk_mode == RiskMode.halted:
            results["reason"] = "Trading halted"
            return results

        if wallet.cash_balance < 100:
            results["reason"] = f"Insufficient cash \u20b9{wallet.cash_balance:.0f}"
            return results

        logger.info(
            f"Auto-execute: cash=\u20b9{wallet.cash_balance:.0f} "
            f"equity=\u20b9{wallet.total_equity:.0f}"
        )

        # Get open positions for heat calculation
        open_result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
        )
        open_rows = open_result.all()

        # --- 4. Get today's signals and build candidates ---
        from services.wallet.risk_manager import MIN_CONFIDENCE, get_sector, compute_atr_stops
        from services.wallet.portfolio_engine import get_portfolio_engine, CandidateSignal
        from services.market_data.fetcher import fetch_latest_price, fetch_historical

        today_start = datetime.combine(
            date.today(), datetime.min.time()
        ).replace(tzinfo=timezone.utc)

        signals_result = await db.execute(
            select(Signal, Asset)
            .join(Asset, Signal.asset_id == Asset.id)
            .where(Signal.created_at >= today_start)
            .where(Signal.confidence >= MIN_CONFIDENCE)
            .where(Signal.action == SignalAction.buy)
            .order_by(desc(Signal.ensemble_score))
            .limit(50)
        )
        raw_signals = signals_result.all()

        # Deduplicate NSE/BSE duplicates
        seen: dict = {}
        for s, a in raw_signals:
            ticker   = a.symbol.split(":")[-1]
            exchange = a.symbol.split(":")[0]
            if ticker not in seen or exchange == "NSE":
                seen[ticker] = (s, a)

        # Trend filter
        candidates = []
        for s, a in seen.values():
            ti = s.technical_indicators or {}
            if ti.get("close_vs_ema50", 0) < 0:
                results["skipped"].append({"symbol": a.symbol, "reason": "below_ema50"})
                continue
            if ti.get("rsi_14", 50) > 75:
                results["skipped"].append({"symbol": a.symbol, "reason": "rsi_overbought"})
                continue
            if ti.get("adx", 0) < 15:
                results["skipped"].append({"symbol": a.symbol, "reason": "adx_too_low"})
                continue
            price = fetch_latest_price(a.symbol)
            if not price:
                results["skipped"].append({"symbol": a.symbol, "reason": "no_price"})
                continue
            sl, tp, _ = compute_atr_stops(a.symbol, price)
            sl_pct = (price - sl) / price
            tp_pct = (tp - price) / price
            candidates.append(CandidateSignal(
                symbol         = a.symbol,
                confidence     = s.confidence,
                sl_pct         = sl_pct,
                tp_pct         = tp_pct,
                ensemble_score = s.ensemble_score,
                sector         = get_sector(a.symbol),
                current_price  = price,
            ))

        logger.info(
            f"{len(candidates)} candidates after trend filter "
            f"({len(raw_signals)} raw, {MIN_CONFIDENCE:.0%} min conf)"
        )

        if not candidates:
            results["reason"] = "No signals passed trend filter"
            return results

        # --- 5. Portfolio engine dynamically allocates ---
        open_positions_heat = [
            {
                "position_size": t.entry_price * t.quantity,
                "sl_pct": (t.entry_price - t.stop_loss) / t.entry_price
                           if t.stop_loss else 0.03,
            }
            for t, _ in open_rows
        ]

        engine     = get_portfolio_engine()
        allocation = engine.construct(
            signals          = candidates,
            total_equity     = wallet.total_equity,
            cash_balance     = wallet.cash_balance,
            open_positions   = open_positions_heat,
            fetch_history_fn = fetch_historical,
        )
        logger.info(allocation.explanation)

        for sig in allocation.rejected:
            results["rejected"].append({"symbol": sig.symbol, "reason": sig.rejection_reason})

        if not allocation.allocations:
            results["reason"] = allocation.explanation
            return results

        # --- 6. Execute the portfolio engine plan ---
        for sig in allocation.allocations:
            try:
                result = await wallet_svc.open_trade_direct(
                    db           = db,
                    asset_symbol = sig.symbol,
                    quantity     = sig.quantity,
                    stop_loss    = round(sig.current_price * (1 - sig.sl_pct), 2),
                    take_profit  = round(sig.current_price * (1 + sig.tp_pct), 2),
                    confidence   = sig.confidence,
                )
                if result.get("approved"):
                    results["executed"].append({
                        "symbol":         sig.symbol,
                        "quantity":       sig.quantity,
                        "entry_price":    sig.current_price,
                        "position_size":  sig.position_size,
                        "allocation_pct": round(sig.final_allocation * 100, 1),
                        "kelly_pct":      round(sig.kelly_fraction * 100, 1),
                        "confidence":     round(sig.confidence * 100, 1),
                    })
                    logger.info(
                        f"OPENED [{len(results['executed'])}/{allocation.positions_out}]: "
                        f"{sig.symbol} qty={sig.quantity} @ \u20b9{sig.current_price:.2f} "
                        f"alloc={sig.final_allocation:.1%} kelly={sig.kelly_fraction:.1%}"
                    )
                else:
                    results["rejected"].append({"symbol": sig.symbol, "reason": result.get("reason")})
            except Exception as e:
                logger.error(f"Failed to open {sig.symbol}: {e}")
                results["rejected"].append({"symbol": sig.symbol, "reason": str(e)})

        await db.commit()

    results["reason"] = (
        f"Portfolio engine: {allocation.positions_out} positions opened, "
        f"{len(results['rejected'])} rejected. "
        f"Heat: {allocation.existing_heat:.1%} -> {allocation.total_heat:.1%}"
    )
    logger.info(results["reason"])
    return results


@celery_app.task(name="workers.tasks.market_tasks.generate_signal_for_symbol")
def generate_signal_for_symbol(symbol: str, headlines: list = None):
    """On-demand signal generation for a single symbol."""
    import asyncio, threading
    result = {}
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_generate_single(symbol, headlines or [])) or {})
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    return result


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
