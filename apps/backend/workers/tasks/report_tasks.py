# workers/tasks/report_tasks.py
# Morning brief, evening debrief, and weekly performance letter.
import sys
import os
import logging
from datetime import date, datetime, timezone

_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from workers.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)

ROOT_CAUSE_MAP = {
    "external_shock":     "Unforeseeable news event — not a model failure",
    "sentiment_miss":     "NLP model misjudged news tone or source credibility",
    "overconfidence":     "High confidence on a weak setup — calibration error",
    "regime_mismatch":    "Trending-market model applied in choppy/ranging conditions",
    "correct_wrong_time": "Direction correct, timing off — common in positional trades",
}


@celery_app.task(name="workers.tasks.report_tasks.generate_morning_report")
def generate_morning_report():
    """Generate morning brief and store in DB. Runs Mon–Fri at 8:35 AM IST."""
    return run_async(_morning_report_async())


async def _morning_report_async() -> dict:
    from core.database import AsyncSessionLocal
    from core.models import DailyReport, ReportType, Signal, Asset, Trade, TradeStatus
    from sqlalchemy import select
    from services.market_data.fetcher import fetch_latest_price
    from models.sentiment.sentiment_service import get_sentiment_service

    today = date.today()
    async with AsyncSessionLocal() as db:
        # Check not already generated today
        existing = await db.execute(
            select(DailyReport)
            .where(DailyReport.report_date == today)
            .where(DailyReport.report_type == ReportType.morning)
        )
        if existing.scalar_one_or_none():
            logger.info("Morning report already exists for today, skipping")
            return {"skipped": True}

        # Top signals from today's scan
        signals_result = await db.execute(
            select(Signal, Asset)
            .join(Asset, Signal.asset_id == Asset.id)
            .where(Signal.created_at >= datetime.combine(today, datetime.min.time()))
            .order_by(Signal.confidence.desc())
            .limit(10)
        )
        signal_rows = signals_result.all()

        watchlist_act  = []
        watchlist_avoid = []

        for signal, asset in signal_rows:
            price = fetch_latest_price(asset.symbol)
            entry = {
                "symbol":     asset.symbol,
                "name":       asset.name,
                "action":     signal.action.value,
                "confidence": round(signal.confidence * 100, 1),
                "regime":     signal.market_regime,
                "rsi":        signal.technical_indicators.get("rsi_14"),
                "price":      round(price, 2) if price else None,
            }
            if signal.confidence >= 0.55 and signal.action.value != "hold":
                watchlist_act.append(entry)
            else:
                watchlist_avoid.append(entry)

        # Open positions status
        open_result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
        )
        positions = []
        for trade, asset in open_result.all():
            price = fetch_latest_price(asset.symbol) or trade.entry_price
            pnl   = (price - trade.entry_price) * trade.quantity
            positions.append({
                "symbol":        asset.symbol,
                "unrealised_pnl": round(pnl, 2),
                "distance_to_stop":   round(price - trade.stop_loss, 2),
                "distance_to_target": round(trade.take_profit - price, 2),
            })

        content = {
            "date":           today.isoformat(),
            "report_type":    "morning",
            "watchlist_act":  watchlist_act[:5],
            "watchlist_avoid": watchlist_avoid[:5],
            "open_positions": positions,
            "signals_scanned": len(signal_rows),
        }

        # LLM narrative
        narrative = await _build_narrative("morning", content)

        report = DailyReport(
            report_date=today,
            report_type=ReportType.morning,
            content=content,
            llm_narrative=narrative,
        )
        db.add(report)
        await db.commit()

    logger.info(f"Morning report generated: {len(watchlist_act)} act, {len(watchlist_avoid)} avoid")
    return {"date": today.isoformat(), "act_count": len(watchlist_act)}


@celery_app.task(name="workers.tasks.report_tasks.generate_evening_report")
def generate_evening_report():
    """Generate evening debrief and score morning predictions. Runs Mon–Fri at 3:30 PM IST."""
    return run_async(_evening_report_async())


async def _evening_report_async() -> dict:
    from core.database import AsyncSessionLocal
    from core.models import (
        DailyReport, ReportType, PredictionOutcome, OutcomeResult,
        Signal, Asset, Trade, TradeStatus,
    )
    from sqlalchemy import select, func
    from services.market_data.fetcher import fetch_latest_price

    today = date.today()
    async with AsyncSessionLocal() as db:
        # Score today's morning predictions against actual market moves
        pending = await db.execute(
            select(PredictionOutcome, Signal, Asset)
            .join(Signal, PredictionOutcome.signal_id == Signal.id)
            .join(Asset, Signal.asset_id == Asset.id)
            .where(PredictionOutcome.outcome == OutcomeResult.pending)
            .where(PredictionOutcome.created_at >= datetime.combine(today, datetime.min.time()))
        )
        rows = pending.all()

        correct = wrong = 0
        for outcome, signal, asset in rows:
            price_now = fetch_latest_price(asset.symbol)
            if price_now is None:
                continue

            # Get price at signal time from technical indicators (close price)
            entry_price = signal.technical_indicators.get("close") or price_now
            actual_delta = (price_now - entry_price) / entry_price if entry_price else 0
            outcome.actual_delta_pct = round(actual_delta * 100, 3)

            predicted_up = outcome.predicted_direction == "up"
            actually_up  = actual_delta > 0.001

            if predicted_up == actually_up:
                outcome.outcome = OutcomeResult.correct
                correct += 1
            else:
                outcome.outcome = OutcomeResult.wrong
                outcome.root_cause = _classify_root_cause(signal, actual_delta)
                wrong += 1

        accuracy = (correct / (correct + wrong) * 100) if (correct + wrong) > 0 else None

        # Today's trade summary
        closed_today = await db.execute(
            select(
                func.count(Trade.id),
                func.coalesce(func.sum(Trade.realized_pnl), 0.0)
            )
            .where(Trade.status == TradeStatus.closed)
            .where(func.date(Trade.exit_time) == today)
        )
        trade_count, total_pnl = closed_today.one()

        content = {
            "date":              today.isoformat(),
            "report_type":       "evening",
            "predictions_scored": correct + wrong,
            "correct":           correct,
            "wrong":             wrong,
            "accuracy_pct":      round(accuracy, 1) if accuracy else None,
            "trades_closed":     int(trade_count),
            "total_pnl":         round(float(total_pnl), 2),
        }

        narrative = await _build_narrative("evening", content)

        report = DailyReport(
            report_date=today,
            report_type=ReportType.evening,
            content=content,
            prediction_accuracy_pct=accuracy,
            llm_narrative=narrative,
        )
        db.add(report)
        await db.flush()  # get report.id before linking outcomes

        # Link scored outcomes to this evening report
        for outcome, _, _ in rows:
            if outcome.outcome != OutcomeResult.pending:
                outcome.report_id = report.id

        await db.commit()

    logger.info(f"Evening report generated: accuracy={accuracy:.1f}%" if accuracy else "Evening report generated")
    return content


@celery_app.task(name="workers.tasks.report_tasks.generate_weekly_report")
def generate_weekly_report():
    """Weekly performance letter. Runs every Sunday at 7:00 PM IST."""
    return run_async(_weekly_report_async())


async def _weekly_report_async() -> dict:
    from core.database import AsyncSessionLocal
    from core.models import DailyReport, ReportType, Trade, TradeStatus
    from sqlalchemy import select, func
    from datetime import timedelta

    today  = date.today()
    week_start = today - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        # Week's trades
        result = await db.execute(
            select(
                func.count(Trade.id),
                func.coalesce(func.sum(Trade.realized_pnl), 0.0),
                func.count(Trade.id).filter(Trade.realized_pnl > 0),
            )
            .where(Trade.status == TradeStatus.closed)
            .where(func.date(Trade.exit_time) >= week_start)
        )
        total_trades, total_pnl, winning_trades = result.one()
        win_rate = (winning_trades / total_trades * 100) if total_trades else 0

        # Average prediction accuracy this week
        acc_result = await db.execute(
            select(func.avg(DailyReport.prediction_accuracy_pct))
            .where(DailyReport.report_type == ReportType.evening)
            .where(DailyReport.report_date >= week_start)
            .where(DailyReport.prediction_accuracy_pct.isnot(None))
        )
        avg_accuracy = acc_result.scalar()

        content = {
            "week_ending":       today.isoformat(),
            "total_trades":      int(total_trades),
            "total_pnl":         round(float(total_pnl), 2),
            "win_rate_pct":      round(win_rate, 1),
            "avg_accuracy_pct":  round(float(avg_accuracy), 1) if avg_accuracy else None,
        }

        narrative = await _build_narrative("weekly", content)

        report = DailyReport(
            report_date=today,
            report_type=ReportType.evening,  # stored as evening type, identified by content
            content={**content, "report_type": "weekly"},
            llm_narrative=narrative,
        )
        db.add(report)
        await db.commit()

    logger.info(f"Weekly report generated: pnl=₹{total_pnl:.2f} win_rate={win_rate:.1f}%")
    return content


# ---------------------------------------------------------------------------
# LLM narrative helper
# ---------------------------------------------------------------------------

async def _build_narrative(report_type: str, content: dict) -> str:
    """Call sentiment service LLM to narrate structured report data."""
    try:
        from models.sentiment.sentiment_service import get_sentiment_service
        import json

        prompts = {
            "morning": (
                f"You are a financial analyst generating a morning market brief. "
                f"Based on this data, write a concise 3-4 sentence market outlook "
                f"covering: overall market tone, top stocks to watch, and key risks today. "
                f"Data: {json.dumps(content, default=str)}"
            ),
            "evening": (
                f"You are a financial analyst generating an evening market debrief. "
                f"Based on this data, write a concise 3-4 sentence summary covering: "
                f"day's performance, where predictions went wrong and why, and "
                f"what to watch tomorrow. Data: {json.dumps(content, default=str)}"
            ),
            "weekly": (
                f"You are a financial analyst generating a weekly performance letter. "
                f"Write a concise 4-5 sentence summary covering: week's P&L, "
                f"win rate assessment, model accuracy, and outlook for next week. "
                f"Data: {json.dumps(content, default=str)}"
            ),
        }

        svc    = get_sentiment_service()
        prompt = prompts.get(report_type, prompts["morning"])

        # Reuse the LLM call infrastructure from sentiment service
        result = await svc._call_nim(prompt) or await svc._call_ollama(prompt)
        if result and isinstance(result, dict):
            # Sentiment service returns JSON — we want raw text here
            # Fall through to direct call below
            pass

        # Direct call for narrative (not JSON format)
        import httpx
        from core.config import settings
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{settings.NVIDIA_NIM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.NVIDIA_NIM_API_KEY}"},
                json={
                    "model": "mistralai/mistral-small-4-119b-2603",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
            )
            return resp.json()["choices"][0]["message"]["content"]

    except Exception as e:
        logger.warning(f"LLM narrative generation failed: {e}")
        return f"Report generated on {date.today().isoformat()}. LLM narrative unavailable."


def _classify_root_cause(signal, actual_delta: float) -> str:
    """Classify why a prediction was wrong based on signal metadata."""
    conf = signal.confidence
    sent = signal.sentiment_score
    rsi  = (signal.technical_indicators or {}).get("rsi_14", 50)

    if abs(actual_delta) > 0.03:                          return "external_shock"
    if conf > 0.75 and abs(actual_delta) < 0.002:        return "overconfidence"
    if abs(sent) > 0.5 and actual_delta * sent < 0:      return "sentiment_miss"
    if (signal.technical_indicators or {}).get("adx", 0) < 20: return "regime_mismatch"
    return "correct_wrong_time"
