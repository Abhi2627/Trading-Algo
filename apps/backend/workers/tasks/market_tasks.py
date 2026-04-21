# workers/tasks/market_tasks.py
# Scheduled tasks for signal generation across all active assets.
import sys
import os
import logging

# Fix sys.path for Celery fork workers — must be before any local imports
_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from workers.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.market_tasks.scan_all_assets", bind=True, max_retries=2)
def scan_all_assets(self):
    """
    Generate signals for every active equity asset.
    Runs Mon–Fri at 8:30 AM IST before market open.
    Retries up to 2 times on transient failures.
    """
    try:
        return run_async(_scan_all_assets_async())
    except Exception as exc:
        logger.error(f"scan_all_assets failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


async def _scan_all_assets_async() -> dict:
    """Async implementation — called by the sync Celery task wrapper."""
    import sys, os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.database import AsyncSessionLocal
    from core.models import Asset, AssetType
    from sqlalchemy import select
    from services.market_data.signal_pipeline import generate_signal

    results = {"generated": 0, "failed": 0, "skipped": 0}

    async with AsyncSessionLocal() as db:
        # Process equities only during market hours scan
        # Crypto runs 24/7 but we still scan once daily for consistency
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
                signal = await generate_signal(
                    symbol=asset.symbol,
                    db=db,
                )
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
                continue  # never let one failure abort the whole scan

        await db.commit()

    logger.info(
        f"Signal scan complete: generated={results['generated']} "
        f"failed={results['failed']} skipped={results['skipped']}"
    )
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
