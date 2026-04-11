# workers/tasks/wallet_tasks.py
# Stop-loss enforcement, intraday force-close, monthly top-up.
import logging
from workers.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.wallet_tasks.check_stop_losses")
def check_stop_losses():
    """
    Check all open trades against current prices.
    Trigger stop-loss or take-profit close if levels are breached.
    Runs every 15 min during market hours Mon–Fri.
    """
    return run_async(_check_stop_losses_async())


async def _check_stop_losses_async() -> dict:
    from core.database import AsyncSessionLocal
    from core.models import Trade, Asset, TradeStatus
    from sqlalchemy import select
    from services.market_data.fetcher import fetch_latest_price
    from services.wallet.wallet_service import get_wallet_service

    stopped = took_profit = 0

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

            reason = None
            if price <= trade.stop_loss:
                reason = "stop_loss_triggered"
            elif price >= trade.take_profit:
                reason = "take_profit_triggered"

            if reason:
                close_result = await wallet_svc.close_trade(
                    db=db,
                    trade_id=str(trade.id),
                    reason=reason,
                )
                if "error" not in close_result:
                    if reason == "stop_loss_triggered":
                        stopped += 1
                    else:
                        took_profit += 1
                    logger.info(
                        f"{reason}: {asset.symbol} "
                        f"price=₹{price} pnl=₹{close_result.get('realized_pnl', 0):+.2f}"
                    )

        if stopped + took_profit > 0:
            await db.commit()

    logger.info(f"Stop-loss check: stopped={stopped} took_profit={took_profit}")
    return {"stopped": stopped, "took_profit": took_profit}


@celery_app.task(name="workers.tasks.wallet_tasks.force_close_intraday")
def force_close_intraday():
    """
    Force-close all open intraday positions at 3:15 PM IST.
    NSE rule: intraday positions must be closed before market close.
    """
    return run_async(_force_close_intraday_async())


async def _force_close_intraday_async() -> dict:
    from core.database import AsyncSessionLocal
    from core.models import Trade, Asset, TradeStatus, TradeType
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
    """
    Add monthly top-up to the paper wallet.
    Runs on the 1st of each month at 9:00 AM IST.
    """
    return run_async(_apply_topup_async())


async def _apply_topup_async() -> dict:
    from core.database import AsyncSessionLocal
    from services.wallet.wallet_service import get_wallet_service

    async with AsyncSessionLocal() as db:
        wallet_svc = get_wallet_service()
        result = await wallet_svc.apply_monthly_topup(db)
        await db.commit()

    logger.info(f"Monthly top-up applied: ₹{result.get('topup_applied', 0)}")
    return result
