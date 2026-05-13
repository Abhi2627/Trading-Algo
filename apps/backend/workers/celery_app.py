# workers/celery_app.py
# Celery instance, beat schedule, and shared async runner.
# All tasks import `celery_app` from here.
import sys
import os

# Ensure backend root is in Python path for all worker processes
_backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from celery import Celery
from celery.schedules import crontab
from core.config import settings

celery_app = Celery(
    "trading_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "workers.tasks.market_tasks",
        "workers.tasks.report_tasks",
        "workers.tasks.wallet_tasks",
        "workers.tasks.retrain_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",       # IST — all schedules are in IST
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,           # re-queue on worker crash
    worker_prefetch_multiplier=1,  # one task at a time per worker
    result_expires=86400,          # keep results 24 hours
)

# ---------------------------------------------------------------------------
# Beat schedule — all times in IST
# ---------------------------------------------------------------------------
celery_app.conf.beat_schedule = {
    # Auto-execute trades at 9:20 AM — 5 min after market opens
    # This is a fallback in case the post-scan trigger fails
    "auto-execute-trades": {
        "task":    "workers.tasks.market_tasks.auto_execute_trades",
        "schedule": crontab(
            hour=9,
            minute=20,
            day_of_week="1-5",
        ),
    },

    # Generate signals for all active assets before market open
    "morning-signal-scan": {
        "task":    "workers.tasks.market_tasks.scan_all_assets",
        "schedule": crontab(
            hour=settings.MORNING_REPORT_HOUR,
            minute=settings.MORNING_REPORT_MINUTE,
            day_of_week="1-5",   # Monday–Friday only
        ),
    },

    # Morning report: market outlook + watchlist
    "morning-report": {
        "task":    "workers.tasks.report_tasks.generate_morning_report",
        "schedule": crontab(
            hour=settings.MORNING_REPORT_HOUR,
            minute=settings.MORNING_REPORT_MINUTE + 5,  # 5 min after signals
            day_of_week="1-5",
        ),
    },

    # Evening report: market debrief + prediction accuracy
    "evening-report": {
        "task":    "workers.tasks.report_tasks.generate_evening_report",
        "schedule": crontab(
            hour=settings.EVENING_REPORT_HOUR,
            minute=settings.EVENING_REPORT_MINUTE,
            day_of_week="1-5",
        ),
    },

    # Stop-loss check every 15 min during market hours (9:15 AM – 3:30 PM IST)
    "stop-loss-check": {
        "task":    "workers.tasks.wallet_tasks.check_stop_losses",
        "schedule": crontab(
            minute="*/15",
            hour="9-15",
            day_of_week="1-5",
        ),
    },

    # Monthly wallet top-up on the 1st of each month at 9:00 AM
    "monthly-topup": {
        "task":    "workers.tasks.wallet_tasks.apply_monthly_topup",
        "schedule": crontab(
            hour=9,
            minute=0,
            day_of_month=1,
        ),
    },

    # Force-close all intraday positions at 3:15 PM (NSE rule)
    "intraday-force-close": {
        "task":    "workers.tasks.wallet_tasks.force_close_intraday",
        "schedule": crontab(
            hour=15,
            minute=15,
            day_of_week="1-5",
        ),
    },

    # Weekly performance report every Sunday at 7:00 PM
    "weekly-report": {
        "task":    "workers.tasks.report_tasks.generate_weekly_report",
        "schedule": crontab(
            hour=19,
            minute=0,
            day_of_week=0,   # Sunday
        ),
    },

    # Weekly model retraining — runs after weekly report, Sunday 8 PM
    "weekly-retrain": {
        "task":    "workers.tasks.retrain_tasks.retrain_models",
        "schedule": crontab(
            hour=20,
            minute=0,
            day_of_week=0,   # Sunday
        ),
    },
}


def run_async(coro):
    """
    Run an async coroutine from a synchronous Celery task.
    Uses a fresh event loop per call to avoid asyncpg loop conflicts.
    """
    import asyncio
    # Create a brand new event loop — never reuse
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        # Close all pending async generators
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)
