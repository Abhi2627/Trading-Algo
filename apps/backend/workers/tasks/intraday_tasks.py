# workers/tasks/intraday_tasks.py
# Intraday trading tasks — scan, execute, monitor, force-close.
#
# Schedule:
#   9:15 AM IST  — intraday_scan (first scan at open)
#   11:00 AM IST — intraday_scan (mid-morning momentum scan)
#   1:00 PM IST  — intraday_scan (post-lunch scan)
#   3:15 PM IST  — intraday_force_close (mandatory close of all intraday)
#
# The intraday monitor runs as a continuous loop (like price_monitor.py)
# checking open intraday positions every 60 seconds.
#
import sys
import os
import logging

_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Intraday-specific risk parameters
INTRADAY_MAX_POSITIONS  = 3      # max concurrent intraday positions
INTRADAY_POSITION_PCT   = 0.08   # max 8% of equity per intraday trade
INTRADAY_MAX_HEAT       = 0.10   # max 10% portfolio heat for intraday
INTRADAY_MIN_CASH       = 500    # don't trade if less than Rs500 available

# Top N symbols to scan intraday (highest liquidity NSE stocks)
INTRADAY_UNIVERSE = [
    "NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK", "NSE:INFY", "NSE:ICICIBANK",
    "NSE:SBIN", "NSE:BHARTIARTL", "NSE:ITC", "NSE:KOTAKBANK", "NSE:LT",
    "NSE:AXISBANK", "NSE:WIPRO", "NSE:ULTRACEMCO", "NSE:SUNPHARMA", "NSE:TITAN",
    "NSE:BAJFINANCE", "NSE:NESTLEIND", "NSE:ADANIENT", "NSE:POWERGRID", "NSE:NTPC",
]


@celery_app.task(name="workers.tasks.intraday_tasks.intraday_scan")
def intraday_scan():
    """
    Scan top liquid NSE stocks for intraday VWAP breakout signals.
    Runs at 9:15 AM, 11:00 AM, 1:00 PM IST.
    """
    import asyncio, threading
    result = {}
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_intraday_scan_async()))
        except Exception as e:
            logger.error(f"intraday_scan failed: {e}")
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    return result


@celery_app.task(name="workers.tasks.intraday_tasks.intraday_force_close")
def intraday_force_close():
    """
    Force-close ALL open intraday positions at 3:15 PM IST.
    NSE rule: no carry-forward of intraday MIS positions.
    """
    import asyncio, threading
    result = {}
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_force_close_async()))
        except Exception as e:
            logger.error(f"intraday_force_close failed: {e}")
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    return result


@celery_app.task(name="workers.tasks.intraday_tasks.intraday_monitor")
def intraday_monitor():
    """
    Continuous intraday position monitor — checks every 60 seconds.
    Runs 9:15 AM to 3:15 PM IST. Started at 9:15 AM by beat.
    Handles: stop-loss, take-profit, trailing stop, VWAP breakdown.
    """
    import asyncio, threading
    result = {}
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_intraday_monitor_async()))
        except Exception as e:
            logger.error(f"intraday_monitor failed: {e}")
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    return result


# ── Async implementations ────────────────────────────────────────────────────

async def _intraday_scan_async() -> dict:
    from datetime import datetime, timezone, timedelta
    from core.database import AsyncSessionLocal
    from core.models import Asset, Trade, TradeStatus, TradeType
    from sqlalchemy import select
    from services.market_data.intraday_fetcher import fetch_5min, compute_intraday_features
    from services.market_data.intraday_signal import generate_intraday_signal, INTRADAY_MAX_HEAT
    from services.wallet.wallet_service import get_wallet_service

    ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    if not (ist_now.replace(hour=9, minute=15) <= ist_now <= ist_now.replace(hour=15, minute=0)):
        return {"skipped": True, "reason": "Outside intraday scan window"}
    if ist_now.weekday() >= 5:
        return {"skipped": True, "reason": "Weekend"}

    results = {"scanned": 0, "signals": [], "executed": [], "rejected": []}

    async with AsyncSessionLocal() as db:
        wallet_svc = get_wallet_service()
        wallet     = await wallet_svc.get_or_create(db)

        if wallet.cash_balance < INTRADAY_MIN_CASH:
            return {"skipped": True, "reason": f"Cash too low: Rs{wallet.cash_balance:.0f}"}

        # Count open intraday positions
        open_intraday = await db.execute(
            select(Trade).where(
                Trade.status == TradeStatus.open,
                Trade.trade_type == TradeType.intraday,
            )
        )
        open_count = len(open_intraday.scalars().all())

        if open_count >= INTRADAY_MAX_POSITIONS:
            return {"skipped": True, "reason": f"Max intraday positions ({INTRADAY_MAX_POSITIONS}) reached"}

        # Compute current intraday heat
        all_open = await db.execute(
            select(Trade).where(Trade.status == TradeStatus.open)
        )
        open_trades = all_open.scalars().all()
        intraday_heat = sum(
            (t.entry_price * t.quantity / wallet.total_equity) * 0.015  # assume 1.5% SL
            for t in open_trades if t.trade_type == TradeType.intraday
        )

        slots = INTRADAY_MAX_POSITIONS - open_count

        # Scan each symbol in intraday universe
        buy_signals = []
        for symbol in INTRADAY_UNIVERSE:
            try:
                df_5min = fetch_5min(symbol, days=2)
                if df_5min is None:
                    continue
                df_feat = compute_intraday_features(df_5min)
                if df_feat is None:
                    continue
                sig = generate_intraday_signal(symbol, df_feat)
                results["scanned"] += 1
                if sig.action == 'buy':
                    buy_signals.append(sig)
                    logger.info(
                        f"Intraday signal: {symbol} BUY "
                        f"conf={sig.confidence:.0%} "
                        f"VWAP={sig.vwap:.2f} RSI={sig.rsi:.1f} "
                        f"vol={sig.vol_spike:.1f}x"
                    )
            except Exception as e:
                logger.warning(f"Intraday scan failed for {symbol}: {e}")

        if not buy_signals:
            results["reason"] = "No intraday signals"
            return results

        # Sort by confidence
        buy_signals.sort(key=lambda s: s.confidence, reverse=True)
        results["signals"] = [
            {"symbol": s.symbol, "confidence": s.confidence, "reason": s.reason}
            for s in buy_signals
        ]

        # Execute top signals within slots and heat budget
        for sig in buy_signals[:slots]:
            # Heat check
            this_heat = (sig.stop_loss and sig.entry_price) and \
                        ((sig.entry_price - sig.stop_loss) / sig.entry_price * INTRADAY_POSITION_PCT) or 0.005
            if intraday_heat + this_heat > INTRADAY_MAX_HEAT:
                results["rejected"].append({
                    "symbol": sig.symbol,
                    "reason": f"Intraday heat budget: {intraday_heat:.1%}+{this_heat:.1%} > {INTRADAY_MAX_HEAT:.0%}"
                })
                continue

            # Position size: smaller than positional, Kelly-lite
            position_size = min(
                wallet.total_equity * INTRADAY_POSITION_PCT * sig.confidence,
                wallet.cash_balance * 0.90,
            )
            if position_size < 500:
                results["rejected"].append({"symbol": sig.symbol, "reason": "Position too small"})
                continue

            quantity = int(position_size // sig.entry_price)
            if quantity == 0:
                results["rejected"].append({
                    "symbol": sig.symbol,
                    "reason": f"Rs{position_size:.0f} < price Rs{sig.entry_price:.0f}"
                })
                continue

            # Open intraday trade
            try:
                result = await wallet_svc.open_trade_direct(
                    db           = db,
                    asset_symbol = sig.symbol,
                    quantity     = quantity,
                    stop_loss    = sig.stop_loss,
                    take_profit  = sig.take_profit,
                    confidence   = sig.confidence,
                    is_intraday  = True,
                )
                if result.get("approved"):
                    results["executed"].append({
                        "symbol":       sig.symbol,
                        "quantity":     quantity,
                        "entry_price":  sig.entry_price,
                        "stop_loss":    sig.stop_loss,
                        "take_profit":  sig.take_profit,
                        "confidence":   sig.confidence,
                        "atr":          sig.atr,
                    })
                    intraday_heat += this_heat
                    logger.info(
                        f"INTRADAY OPENED: {sig.symbol} qty={quantity} "
                        f"@ Rs{sig.entry_price:.2f} "
                        f"SL=Rs{sig.stop_loss} TP=Rs{sig.take_profit}"
                    )
                else:
                    results["rejected"].append({
                        "symbol": sig.symbol,
                        "reason": result.get("reason")
                    })
            except Exception as e:
                logger.error(f"Intraday open failed for {sig.symbol}: {e}")
                results["rejected"].append({"symbol": sig.symbol, "reason": str(e)})

        await db.commit()

    return results


async def _force_close_async() -> dict:
    """Force-close all open intraday positions at 3:15 PM."""
    from core.database import AsyncSessionLocal
    from core.models import Trade, Asset, TradeStatus, TradeType
    from sqlalchemy import select
    from services.wallet.wallet_service import get_wallet_service

    closed = 0
    results = {"closed": [], "errors": []}

    async with AsyncSessionLocal() as db:
        wallet_svc = get_wallet_service()
        open_result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
            .where(Trade.trade_type == TradeType.intraday)
        )
        trades = open_result.all()

        if not trades:
            logger.info("Intraday force-close: no open intraday positions")
            return {"closed": [], "errors": [], "message": "Nothing to close"}

        for trade, asset in trades:
            try:
                result = await wallet_svc.close_trade(
                    db       = db,
                    trade_id = str(trade.id),
                    reason   = "intraday_force_close_3pm",
                )
                if "error" not in result:
                    closed += 1
                    results["closed"].append({
                        "symbol":       asset.symbol,
                        "pnl":          result.get("realized_pnl", 0),
                        "exit_price":   result.get("exit_price", 0),
                    })
                    logger.info(
                        f"Force-closed: {asset.symbol} "
                        f"pnl=Rs{result.get('realized_pnl', 0):+.2f}"
                    )
                else:
                    results["errors"].append({"symbol": asset.symbol, "error": result["error"]})
            except Exception as e:
                logger.error(f"Force-close failed for {asset.symbol}: {e}")
                results["errors"].append({"symbol": asset.symbol, "error": str(e)})

        if closed > 0:
            await db.commit()

    logger.info(f"Intraday force-close complete: {closed} positions closed")
    return results


async def _intraday_monitor_async() -> dict:
    """
    Monitor loop for open intraday positions. Runs every 60 seconds
    from 9:15 AM until 3:15 PM IST, then exits.
    """
    import asyncio
    from datetime import datetime, timezone, timedelta
    from core.database import AsyncSessionLocal
    from core.models import Trade, Asset, TradeStatus, TradeType
    from sqlalchemy import select
    from services.market_data.fetcher import fetch_latest_price
    from services.market_data.intraday_signal import check_intraday_exit
    from services.wallet.wallet_service import get_wallet_service

    POLL_INTERVAL = 60   # seconds
    checks = 0
    exits  = 0

    def ist_now():
        return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

    def in_window():
        n = ist_now()
        return (n.weekday() < 5 and
                n.replace(hour=9,  minute=15) <= n <=
                n.replace(hour=15, minute=15))

    while in_window():
        try:
            async with AsyncSessionLocal() as db:
                wallet_svc   = get_wallet_service()
                open_result  = await db.execute(
                    select(Trade, Asset)
                    .join(Asset, Trade.asset_id == Asset.id)
                    .where(Trade.status == TradeStatus.open)
                    .where(Trade.trade_type == TradeType.intraday)
                )
                positions = open_result.all()

                if not positions:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                for trade, asset in positions:
                    price = fetch_latest_price(asset.symbol)
                    if not price:
                        continue

                    # Track peak price via notes
                    peak_price = trade.entry_price
                    if trade.notes and "peak:" in trade.notes:
                        try:
                            peak_price = float(trade.notes.split("peak:")[1].split()[0])
                        except Exception:
                            pass
                    peak_price = max(peak_price, price)

                    # Extract ATR from notes or use 0.5% of price
                    atr = price * 0.005
                    if trade.notes and "atr:" in trade.notes:
                        try:
                            atr = float(trade.notes.split("atr:")[1].split()[0])
                        except Exception:
                            pass

                    reason = check_intraday_exit(
                        entry_price   = trade.entry_price,
                        stop_loss     = trade.stop_loss,
                        take_profit   = trade.take_profit,
                        atr           = atr,
                        current_price = price,
                        peak_price    = peak_price,
                    )

                    if reason:
                        result = await wallet_svc.close_trade(
                            db       = db,
                            trade_id = str(trade.id),
                            reason   = reason,
                        )
                        if "error" not in result:
                            exits += 1
                            logger.info(
                                f"Intraday exit: {asset.symbol} "
                                f"reason={reason} "
                                f"pnl=Rs{result.get('realized_pnl', 0):+.2f}"
                            )
                        await db.commit()
                    else:
                        # Update peak price in notes
                        if peak_price > trade.entry_price:
                            notes = trade.notes or ""
                            if "peak:" in notes:
                                parts = notes.split("peak:")
                                rest  = parts[1].split(None, 1)
                                trade.notes = parts[0] + f"peak:{peak_price:.2f}" + \
                                              (" " + rest[1] if len(rest) > 1 else "")
                            else:
                                trade.notes = (notes + f" peak:{peak_price:.2f}").strip()
                            await db.commit()

                    checks += 1

        except Exception as e:
            logger.error(f"Intraday monitor error: {e}")

        await asyncio.sleep(POLL_INTERVAL)

    logger.info(f"Intraday monitor ended: checks={checks} exits={exits}")
    return {"checks": checks, "exits": exits}
