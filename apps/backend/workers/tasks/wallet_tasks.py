# workers/tasks/wallet_tasks.py
# Stop-loss enforcement, intraday force-close, monthly top-up.
import sys
import os
import logging

_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from workers.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.wallet_tasks.monitor_positions")
def monitor_positions():
    """
    Real-time position monitor — polls open positions every 30 seconds.
    Runs from 9:15 AM to 3:30 PM IST, Mon-Fri.
    Runs in its own thread with a dedicated event loop to avoid
    conflicting with other Celery tasks on the same worker.
    """
    import asyncio
    import threading

    result = {}

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            nonlocal result
            result = loop.run_until_complete(_monitor_positions_async())
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()  # block until market close (3:30 PM IST)
    return result


async def _monitor_positions_async() -> dict:
    from services.market_data.price_monitor import run_price_monitor
    return await run_price_monitor()


@celery_app.task(name="workers.tasks.wallet_tasks.check_stop_losses")
def check_stop_losses():
    """
    Check all open trades against current prices every 15 min (safety fallback).
    """
    import asyncio, threading
    result = {}
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_check_stop_losses_async()))
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    return result


async def _check_stop_losses_async() -> dict:
    from core import database as _db_module
    await _db_module.engine.dispose()
    from core.database import AsyncSessionLocal
    from core.models import Trade, Asset, TradeStatus
    from sqlalchemy import select
    from services.market_data.fetcher import fetch_latest_price
    from services.wallet.wallet_service import get_wallet_service
    from services.wallet.risk_manager import STOP_LOSS_PCT as _SL, TAKE_PROFIT_PCT as _TP, TIME_EXIT_DAYS
    from datetime import datetime, timezone

    # Use constants from risk_manager so everything stays in sync
    TRAIL_ACTIVATE_PCT = 0.07   # trailing stop activates once up 7%
    TRAIL_PCT          = 0.06   # trail sits 6% below peak price
    TAKE_PROFIT_PCT    = _TP    # 0.08 — hard take-profit
    STOP_LOSS_PCT      = _SL    # 0.03 — hard stop-loss

    stopped = took_profit = trailing_stopped = time_exited = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
        )
        rows = result.all()

        wallet_svc = get_wallet_service()

        for trade, asset in rows:
            price = fetch_latest_price(asset.symbol)
            if price is None:
                continue

            entry      = trade.entry_price
            gain_pct   = (price - entry) / entry

            # Update peak price stored in trade notes
            # We store peak as "peak:XXXX.XX" in notes field
            peak_price = entry
            if trade.notes and 'peak:' in trade.notes:
                try:
                    peak_price = float(trade.notes.split('peak:')[1].split()[0])
                except Exception:
                    peak_price = entry

            if price > peak_price:
                peak_price = price
                # Update notes with new peak
                existing_note = trade.notes or ''
                if 'peak:' in existing_note:
                    parts = existing_note.split('peak:')
                    rest  = parts[1].split(None, 1)
                    existing_note = parts[0] + f'peak:{peak_price:.2f}' + (' ' + rest[1] if len(rest) > 1 else '')
                else:
                    existing_note = (existing_note + f' peak:{peak_price:.2f}').strip()
                trade.notes = existing_note

            # Determine exit reason
            reason = None

            # 1. Hard stop-loss — always active
            hard_stop = entry * (1 - STOP_LOSS_PCT)
            if price <= hard_stop:
                reason = 'stop_loss_triggered'

            # 2. Trailing stop — activates once gain >= TRAIL_ACTIVATE_PCT
            elif gain_pct >= TRAIL_ACTIVATE_PCT:
                trailing_stop = peak_price * (1 - TRAIL_PCT)
                if price <= trailing_stop:
                    reason = 'trailing_stop_triggered'
                    logger.info(
                        f"Trailing stop: {asset.symbol} "
                        f"entry=₹{entry} peak=₹{peak_price:.2f} "
                        f"trail=₹{trailing_stop:.2f} current=₹{price}"
                    )

            # 3. Hard take-profit
            hard_tp = entry * (1 + TAKE_PROFIT_PCT)
            if price >= hard_tp:
                reason = 'take_profit_triggered'

            # 4. Time-based exit — exit after TIME_EXIT_DAYS if not profitable
            #    This frees up capital that's just sitting flat/down.
            #    Only triggers if we haven't already hit SL/TP above.
            if reason is None:
                days_held = (
                    datetime.now(timezone.utc) - trade.entry_time
                ).total_seconds() / 86400
                if days_held >= TIME_EXIT_DAYS and gain_pct <= 0:
                    reason = 'time_exit_not_profitable'
                    logger.info(
                        f"Time exit: {asset.symbol} held {days_held:.1f}d "
                        f"gain={gain_pct:+.2%} — freeing capital"
                    )

            if reason:
                close_result = await wallet_svc.close_trade(
                    db=db,
                    trade_id=str(trade.id),
                    reason=reason,
                )
                if 'error' not in close_result:
                    if reason == 'stop_loss_triggered':
                        stopped += 1
                    elif reason == 'trailing_stop_triggered':
                        trailing_stopped += 1
                    elif reason == 'time_exit_not_profitable':
                        time_exited += 1
                    else:
                        took_profit += 1
                    logger.info(
                        f"{reason}: {asset.symbol} "
                        f"price=₹{price:.2f} "
                        f"pnl=₹{close_result.get('realized_pnl', 0):+.2f}"
                    )

        if stopped + took_profit + trailing_stopped + time_exited > 0:
            await db.commit()

    logger.info(
        f"Stop-loss check: stopped={stopped} trailing_stopped={trailing_stopped} "
        f"took_profit={took_profit} time_exited={time_exited}"
    )
    return {
        'stopped':          stopped,
        'trailing_stopped': trailing_stopped,
        'took_profit':      took_profit,
        'time_exited':      time_exited,
    }


@celery_app.task(name="workers.tasks.wallet_tasks.force_close_intraday")
def force_close_intraday():
    import asyncio, threading
    result = {}
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_force_close_intraday_async()))
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    return result


async def _force_close_intraday_async() -> dict:
    from core import database as _db_module
    await _db_module.engine.dispose()
    from core.database import AsyncSessionLocal
    from sqlalchemy import select
    from services.wallet.wallet_service import get_wallet_service

    closed = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Trade)
            .where(Trade.status == TradeStatus.open)
            .where(Trade.trade_type == TradeType.intraday)
        )
        trades = result.scalars().all()
        wallet_svc = get_wallet_service()

        for trade in trades:
            res = await wallet_svc.close_trade(
                db=db,
                trade_id=str(trade.id),
                reason="intraday_force_close_315pm",
            )
            if "error" not in res:
                closed += 1

        if closed > 0:
            await db.commit()

    logger.info(f"Intraday force-close: {closed} positions closed")
    return {"force_closed": closed}


@celery_app.task(name="workers.tasks.wallet_tasks.apply_monthly_topup")
def apply_monthly_topup():
    import asyncio, threading
    result = {}
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_apply_topup_async()))
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    return result


async def _apply_topup_async() -> dict:
    from core import database as _db_module
    await _db_module.engine.dispose()
    from core.database import AsyncSessionLocal
    from services.wallet.wallet_service import get_wallet_service

    async with AsyncSessionLocal() as db:
        wallet_svc = get_wallet_service()
        result = await wallet_svc.apply_monthly_topup(db)
        await db.commit()

    logger.info(f"Monthly top-up applied: ₹{result.get('topup_applied', 0)}")
    return result
