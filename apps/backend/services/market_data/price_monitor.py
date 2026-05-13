# services/market_data/price_monitor.py
# Real-time position monitor — polls NSE prices every 30 seconds for open positions.
#
# Why not true WebSocket:
#   NSE's WebSocket (used by Kite/Zerodha) requires authenticated browser sessions
#   that expire within minutes. Not viable for a 24/7 server without Zerodha API.
#
# This approach: tight 30-second poll loop ONLY for symbols with open positions.
#   - 15 min Celery beat → safety net (kept as fallback)
#   - 30 sec monitor loop → primary real-time SL/TP enforcement
#   - Only runs during market hours (9:15 AM – 3:30 PM IST, Mon–Fri)
#   - Stops itself when no positions are open (zero overhead)
#
import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

POLL_INTERVAL_S  = 30     # check every 30 seconds
MARKET_OPEN_H    = 9
MARKET_OPEN_M    = 15
MARKET_CLOSE_H   = 15
MARKET_CLOSE_M   = 30


def _ist_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def _is_market_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    open_  = now.replace(hour=MARKET_OPEN_H,  minute=MARKET_OPEN_M,  second=0, microsecond=0)
    close_ = now.replace(hour=MARKET_CLOSE_H, minute=MARKET_CLOSE_M, second=0, microsecond=0)
    return open_ <= now <= close_


async def _get_open_positions() -> list[dict]:
    """Return list of open trades with symbol, entry_price, stop_loss, take_profit, trade_id."""
    from core.database import AsyncSessionLocal
    from core.models import Trade, Asset, TradeStatus
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
        )
        rows = result.all()
        return [
            {
                "trade_id":    str(t.id),
                "symbol":      a.symbol,
                "entry_price": t.entry_price,
                "stop_loss":   t.stop_loss,
                "take_profit": t.take_profit,
                "entry_time":  t.entry_time,
                "notes":       t.notes or "",
            }
            for t, a in rows
        ]


async def _check_position(pos: dict) -> None:
    """Check a single position against current price and close if needed."""
    from services.market_data.fetcher import fetch_latest_price
    from services.wallet.wallet_service import get_wallet_service
    from services.wallet.risk_manager import TIME_EXIT_DAYS
    from core.database import AsyncSessionLocal

    symbol = pos["symbol"]
    price  = fetch_latest_price(symbol)
    if price is None:
        logger.debug(f"PriceMonitor: no price for {symbol}")
        return

    entry      = pos["entry_price"]
    stop_loss  = pos["stop_loss"]
    take_profit = pos["take_profit"]
    gain_pct   = (price - entry) / entry

    # Track peak price via notes field (same as wallet_tasks.py)
    peak_price = entry
    notes = pos.get("notes", "")
    if "peak:" in notes:
        try:
            peak_price = float(notes.split("peak:")[1].split()[0])
        except Exception:
            peak_price = entry
    peak_price = max(peak_price, price)

    # Determine if exit is needed
    reason = None

    # 1. Hard stop-loss
    if price <= stop_loss:
        reason = "stop_loss_triggered"

    # 2. Trailing stop (activates at +7%)
    elif gain_pct >= 0.07:
        trailing_stop = peak_price * 0.94  # 6% below peak
        if price <= trailing_stop:
            reason = "trailing_stop_triggered"
            logger.info(
                f"PriceMonitor trailing stop: {symbol} "
                f"peak=₹{peak_price:.2f} trail=₹{trailing_stop:.2f} current=₹{price:.2f}"
            )

    # 3. Hard take-profit
    if price >= take_profit:
        reason = "take_profit_triggered"

    # 4. Time exit
    if reason is None:
        days_held = (
            datetime.now(timezone.utc) - pos["entry_time"]
        ).total_seconds() / 86400
        if days_held >= TIME_EXIT_DAYS and gain_pct <= 0:
            reason = "time_exit_not_profitable"

    if reason:
        logger.info(
            f"PriceMonitor exit: {symbol} reason={reason} "
            f"price=₹{price:.2f} entry=₹{entry:.2f} gain={gain_pct:+.2%}"
        )
        async with AsyncSessionLocal() as db:
            wallet_svc = get_wallet_service()
            result = await wallet_svc.close_trade(
                db=db,
                trade_id=pos["trade_id"],
                reason=reason,
            )
            if "error" not in result:
                await db.commit()
                logger.info(
                    f"PriceMonitor closed: {symbol} "
                    f"pnl=₹{result.get('realized_pnl', 0):+.2f}"
                )
            else:
                logger.warning(f"PriceMonitor close failed: {symbol} — {result['error']}")
    else:
        # Update peak price in DB if it moved up
        if peak_price > entry and f"peak:{peak_price:.2f}" not in notes:
            from core.database import AsyncSessionLocal
            from core.models import Trade
            from sqlalchemy import select
            import uuid
            async with AsyncSessionLocal() as db:
                trade_result = await db.execute(
                    select(Trade).where(Trade.id == uuid.UUID(pos["trade_id"]))
                )
                trade = trade_result.scalar_one_or_none()
                if trade:
                    existing = trade.notes or ""
                    if "peak:" in existing:
                        parts = existing.split("peak:")
                        rest  = parts[1].split(None, 1)
                        trade.notes = parts[0] + f"peak:{peak_price:.2f}" + (
                            " " + rest[1] if len(rest) > 1 else ""
                        )
                    else:
                        trade.notes = (existing + f" peak:{peak_price:.2f}").strip()
                    await db.commit()


async def run_price_monitor() -> dict:
    """
    Main monitor loop. Runs for one market session (9:15 AM – 3:30 PM IST).
    Called by the Celery task at 9:15 AM. Exits automatically at market close.
    """
    logger.info("PriceMonitor: starting real-time position monitor")
    checks = 0
    exits  = 0

    while _is_market_open():
        positions = await _get_open_positions()

        if not positions:
            logger.debug("PriceMonitor: no open positions — sleeping")
            await asyncio.sleep(POLL_INTERVAL_S)
            continue

        logger.debug(f"PriceMonitor: checking {len(positions)} position(s)")

        for pos in positions:
            try:
                await _check_position(pos)
                checks += 1
            except Exception as e:
                logger.error(f"PriceMonitor error for {pos['symbol']}: {e}")

        await asyncio.sleep(POLL_INTERVAL_S)

    logger.info(f"PriceMonitor: session ended. checks={checks} exits={exits}")
    return {"checks": checks, "exits": exits}
