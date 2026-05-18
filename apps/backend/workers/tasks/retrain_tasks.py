# workers/tasks/retrain_tasks.py
# ML model retraining pipeline via Kaggle.
#
# Flow:
#   1. Export signal_outcome table -> CSV
#   2. Push CSV to a Kaggle dataset (versioned)
#   3. Trigger the Kaggle notebook run
#   4. Poll until complete (up to 2 hours)
#   5. Download transformer.pth + transformer_scaler.pkl -> data/trained_models/
#   6. Reload the in-memory forecaster
#
# Triggered: weekly (Sunday 8 PM IST) + manually via POST /wallet/retrain
# Guards:    skip if < MIN_SAMPLES outcomes in DB
import sys
import os
import logging
from datetime import date

_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from workers.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)

MIN_SAMPLES     = 10    # don't retrain with fewer than this many closed outcomes
POLL_INTERVAL_S = 60    # how often to poll Kaggle for notebook status (seconds)
MAX_POLL_TRIES  = 120   # 120 x 60s = 2 hours max wait


@celery_app.task(name="workers.tasks.retrain_tasks.retrain_models")
def retrain_models():
    """
    Weekly retraining pipeline. Runs Sunday at 8 PM IST.
    Also callable manually via POST /wallet/retrain (admin only).
    """
    return run_async(_retrain_async())


async def _retrain_async() -> dict:
    from core.config import settings
    import json
    from datetime import datetime, timezone

    run_start = datetime.now(timezone.utc)

    async def _persist_result(result: dict):
        """Store retrain result in DB for visibility via API."""
        try:
            from core.database import AsyncSessionLocal
            from core.models import PaperWallet
            from sqlalchemy import select
            async with AsyncSessionLocal() as db:
                wallet_r = await db.execute(select(PaperWallet).limit(1))
                wallet = wallet_r.scalar_one_or_none()
                if wallet:
                    existing = {}
                    if wallet.notes:
                        try:
                            existing = json.loads(wallet.notes)
                        except Exception:
                            existing = {}
                    existing['last_retrain'] = {
                        **result,
                        'run_at': run_start.isoformat(),
                        'finished_at': datetime.now(timezone.utc).isoformat(),
                    }
                    wallet.notes = json.dumps(existing)
                    await db.commit()
                    logger.info("Retrain result persisted to DB")
        except Exception as e:
            logger.warning(f"Failed to persist retrain result: {e}")

    # Guard: skip if Kaggle not configured
    if not settings.KAGGLE_USERNAME or not settings.KAGGLE_API_KEY:
        logger.warning("Kaggle credentials not configured — skipping retraining")
        result = {"skipped": True, "reason": "kaggle_not_configured", "success": False}
        await _persist_result(result)
        return result

    if not settings.KAGGLE_NOTEBOOK_ID or not settings.KAGGLE_DATASET_ID:
        logger.warning("KAGGLE_NOTEBOOK_ID or KAGGLE_DATASET_ID not set — skipping")
        result = {"skipped": True, "reason": "notebook_or_dataset_not_configured", "success": False}
        await _persist_result(result)
        return result

    # 1. Count available training samples
    sample_count = await _count_outcomes()
    if sample_count < MIN_SAMPLES:
        logger.info(f"Only {sample_count} outcomes available, need {MIN_SAMPLES} — skipping")
        result = {"skipped": True, "reason": "insufficient_samples", "count": sample_count, "success": False}
        await _persist_result(result)
        return result

    logger.info(f"Starting retraining pipeline with {sample_count} outcome samples")

    # 2. Export signal_outcome -> CSV
    csv_path = await _export_outcomes_csv()
    logger.info(f"Exported {sample_count} outcomes to {csv_path}")

    # 3. Push CSV to Kaggle dataset
    version_note = f"Auto-export {date.today().isoformat()} ({sample_count} samples)"
    await _push_to_kaggle_dataset(csv_path, version_note, settings)
    logger.info(f"Pushed dataset version: {version_note}")

    # 4. Trigger notebook run
    kernel_slug = await _trigger_kaggle_notebook(settings)
    logger.info(f"Triggered notebook: {kernel_slug}")

    # 5. Poll for completion
    success = await _poll_notebook(kernel_slug, settings)
    if not success:
        logger.error("Kaggle notebook failed or timed out")
        result = {"success": False, "reason": "notebook_failed_or_timeout", "samples_used": sample_count}
        await _persist_result(result)
        return result

    # 6. Download model files
    downloaded = await _download_model_files(kernel_slug, settings)
    logger.info(f"Downloaded: {downloaded}")

    # 7. Hot-reload forecaster in this worker process
    _reload_forecaster()

    result = {
        "success":       True,
        "samples_used":  sample_count,
        "kernel_slug":   kernel_slug,
        "files_updated": downloaded,
        "retrained_at":  date.today().isoformat(),
    }
    await _persist_result(result)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _count_outcomes() -> int:
    from core.database import AsyncSessionLocal
    from core.models import SignalOutcome, OutcomeResult
    from sqlalchemy import select, func
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count()).select_from(SignalOutcome)
            .where(SignalOutcome.outcome != OutcomeResult.pending)
        )
        return result.scalar() or 0


async def _export_outcomes_csv() -> str:
    """Export signal_outcome table to a temp CSV for Kaggle upload."""
    import csv
    import tempfile
    from core.database import AsyncSessionLocal
    from core.models import SignalOutcome, OutcomeResult
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SignalOutcome)
            .where(SignalOutcome.outcome != OutcomeResult.pending)
            .order_by(SignalOutcome.opened_at)
        )
        outcomes = result.scalars().all()

    csv_path = os.path.join(tempfile.gettempdir(), "signal_outcomes.csv")
    fields = [
        "symbol", "signal_action", "signal_confidence", "entry_price",
        "exit_price", "exit_reason", "realized_pnl", "pnl_pct",
        "days_held", "outcome", "ensemble_score", "market_regime",
        "opened_at", "closed_at",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for o in outcomes:
            writer.writerow({
                "symbol":            o.symbol,
                "signal_action":     o.signal_action,
                "signal_confidence": o.signal_confidence,
                "entry_price":       o.entry_price,
                "exit_price":        o.exit_price,
                "exit_reason":       o.exit_reason,
                "realized_pnl":      o.realized_pnl,
                "pnl_pct":           o.pnl_pct,
                "days_held":         o.days_held,
                "outcome":           o.outcome.value,
                "ensemble_score":    o.ensemble_score,
                "market_regime":     o.market_regime,
                "opened_at":         o.opened_at.isoformat() if o.opened_at else None,
                "closed_at":         o.closed_at.isoformat() if o.closed_at else None,
            })
    return csv_path


async def _push_to_kaggle_dataset(csv_path: str, version_note: str, settings) -> None:
    """Upload CSV as a new version of the Kaggle dataset."""
    import json
    import subprocess

    # Write ~/.kaggle/kaggle.json for CLI auth
    kaggle_dir  = os.path.expanduser("~/.kaggle")
    os.makedirs(kaggle_dir, exist_ok=True)
    kaggle_json = os.path.join(kaggle_dir, "kaggle.json")
    with open(kaggle_json, "w") as f:
        json.dump({"username": settings.KAGGLE_USERNAME, "key": settings.KAGGLE_API_KEY}, f)
    os.chmod(kaggle_json, 0o600)

    # Create dataset-metadata.json alongside the CSV
    csv_dir = os.path.dirname(csv_path)
    with open(os.path.join(csv_dir, "dataset-metadata.json"), "w") as f:
        json.dump({
            "title":    "algotrade-signal-outcomes",
            "id":       settings.KAGGLE_DATASET_ID,
            "licenses": [{"name": "CC0-1.0"}],
        }, f)

    result = subprocess.run(
        ["kaggle", "datasets", "version", "-p", csv_dir,
         "-m", version_note, "--dir-mode", "zip"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Kaggle dataset push failed: {result.stderr}")
    logger.info(f"Dataset pushed: {result.stdout.strip()}")


async def _trigger_kaggle_notebook(settings) -> str:
    """Trigger a new run of the retraining notebook via Kaggle REST API."""
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://www.kaggle.com/api/v1/kernels/{settings.KAGGLE_NOTEBOOK_ID}/run",
            auth=(settings.KAGGLE_USERNAME, settings.KAGGLE_API_KEY),
            json={},
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to trigger notebook ({resp.status_code}): {resp.text}"
            )
    return settings.KAGGLE_NOTEBOOK_ID


async def _poll_notebook(kernel_slug: str, settings) -> bool:
    """Poll Kaggle until notebook is complete, failed, or timed out."""
    import asyncio
    import httpx

    for attempt in range(MAX_POLL_TRIES):
        await asyncio.sleep(POLL_INTERVAL_S)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"https://www.kaggle.com/api/v1/kernels/{kernel_slug}",
                    auth=(settings.KAGGLE_USERNAME, settings.KAGGLE_API_KEY),
                )
            if resp.status_code != 200:
                logger.warning(f"Kaggle poll HTTP {resp.status_code}")
                continue

            status = resp.json().get("status", "unknown")
            logger.info(f"Notebook [{attempt+1}/{MAX_POLL_TRIES}]: {status}")

            if status == "complete":
                return True
            if status in ("error", "cancelled"):
                logger.error(f"Notebook terminal status: {status}")
                return False
        except Exception as e:
            logger.warning(f"Poll error: {e}")

    logger.error("Notebook timed out after 2 hours")
    return False


async def _download_model_files(kernel_slug: str, settings) -> list:
    """Download model output files from the completed notebook."""
    import subprocess
    from pathlib import Path

    models_dir = Path(_backend_root) / "data" / "trained_models"
    models_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["kaggle", "kernels", "output", kernel_slug, "-p", str(models_dir)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Model download failed: {result.stderr}")

    downloaded = []
    for fname in ["transformer.pth", "transformer_scaler.pkl"]:
        if (models_dir / fname).exists():
            downloaded.append(fname)
        else:
            logger.warning(f"Expected output not found: {fname}")

    return downloaded


def _reload_forecaster():
    """Hot-reload the in-memory forecaster singleton after retraining."""
    try:
        from models.transformer import forecaster as fm
        fm._forecaster = None
        fresh = fm.get_forecaster()
        if fresh.is_ready:
            logger.info("Forecaster hot-reloaded successfully")
        else:
            logger.warning("Forecaster not ready after reload — check model files")
    except Exception as e:
        logger.warning(f"Forecaster reload failed: {e}")
