# services/strategy/auto_tuner.py
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)
MIN_SAMPLES_FOR_TUNING = 15


@dataclass
class TuningResult:
    sufficient_data:  bool
    sample_count:     int
    current_params:   dict
    suggested_params: dict
    changes:          list
    reasoning:        list
    confidence:       float
    skip_reason:      str = ''


async def analyze_and_suggest() -> TuningResult:
    from core.database import AsyncSessionLocal
    from core.models import SignalOutcome
    from sqlalchemy import select
    from services.wallet.risk_manager import (
        MIN_CONFIDENCE, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
        TIME_EXIT_DAYS, ATR_SL_MULT, ATR_TP_MULT
    )

    current = {
        "MIN_CONFIDENCE":  MIN_CONFIDENCE,
        "STOP_LOSS_PCT":   STOP_LOSS_PCT,
        "TAKE_PROFIT_PCT": TAKE_PROFIT_PCT,
        "TIME_EXIT_DAYS":  TIME_EXIT_DAYS,
        "ATR_SL_MULT":     ATR_SL_MULT,
        "ATR_TP_MULT":     ATR_TP_MULT,
    }

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SignalOutcome)
            .where(SignalOutcome.outcome != 'pending')
            .order_by(SignalOutcome.closed_at.desc())
            .limit(100)
        )
        outcomes = result.scalars().all()

    n = len(outcomes)
    if n < MIN_SAMPLES_FOR_TUNING:
        return TuningResult(
            sufficient_data=False, sample_count=n,
            current_params=current, suggested_params=current,
            changes=[], reasoning=[], confidence=0.0,
            skip_reason=f"Only {n} closed trades — need {MIN_SAMPLES_FOR_TUNING}"
        )

    wins  = [o for o in outcomes if str(o.outcome).endswith('correct')]
    loss  = [o for o in outcomes if str(o.outcome).endswith('wrong')]
    suggested = dict(current)
    changes   = []
    reasoning = []

    # 1. Confidence threshold
    buckets = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
    bucket_stats = {}
    for lo in buckets:
        subset = [o for o in outcomes if o.signal_confidence >= lo]
        if len(subset) >= 5:
            w = sum(1 for o in subset if str(o.outcome).endswith('correct'))
            bucket_stats[lo] = {"count": len(subset), "win_rate": w / len(subset)}

    if bucket_stats:
        best_t = max(bucket_stats, key=lambda t: bucket_stats[t]["win_rate"] * (bucket_stats[t]["count"] ** 0.5))
        if abs(best_t - current["MIN_CONFIDENCE"]) >= 0.05:
            direction = "Raising" if best_t > current["MIN_CONFIDENCE"] else "Lowering"
            suggested["MIN_CONFIDENCE"] = round(best_t, 2)
            changes.append(f"MIN_CONFIDENCE: {current['MIN_CONFIDENCE']:.0%} → {best_t:.0%}")
            reasoning.append(f"{direction} confidence threshold to {best_t:.0%} gives {bucket_stats[best_t]['win_rate']:.0%} win rate")

    # 2. Time exit
    time_exits = [o for o in outcomes if o.exit_reason == 'time_exit_not_profitable']
    if len(time_exits) >= 3:
        nearly_flat = [o for o in time_exits if abs(o.pnl_pct or 0) < 0.01]
        if len(nearly_flat) / len(time_exits) > 0.5:
            new_te = min(current["TIME_EXIT_DAYS"] + 2, 14)
            suggested["TIME_EXIT_DAYS"] = new_te
            changes.append(f"TIME_EXIT_DAYS: {current['TIME_EXIT_DAYS']} → {new_te}")
            reasoning.append(f"{len(nearly_flat)}/{len(time_exits)} time exits were nearly flat — extending hold")

    # 3. SL/TP multipliers
    sl_exits = [o for o in loss if o.exit_reason == 'stop_loss_triggered']
    tp_exits = [o for o in wins if o.exit_reason == 'take_profit_triggered']

    if len(loss) >= 5 and len(sl_exits) / len(loss) > 0.60:
        new_sl = round(min(current["ATR_SL_MULT"] + 0.25, 3.0), 2)
        if new_sl != current["ATR_SL_MULT"]:
            suggested["ATR_SL_MULT"] = new_sl
            changes.append(f"ATR_SL_MULT: {current['ATR_SL_MULT']} → {new_sl}")
            reasoning.append(f"{len(sl_exits)}/{len(loss)} losses hit SL — widening stop")

    if len(wins) >= 5 and len(tp_exits) / len(wins) < 0.20:
        new_tp = round(max(current["ATR_TP_MULT"] - 0.5, 2.0), 2)
        if new_tp != current["ATR_TP_MULT"]:
            suggested["ATR_TP_MULT"] = new_tp
            changes.append(f"ATR_TP_MULT: {current['ATR_TP_MULT']} → {new_tp}")
            reasoning.append(f"TP rarely hit ({len(tp_exits)}/{len(wins)} wins) — reducing multiplier")

    # 4. Regime warnings
    regime_stats = {}
    for o in outcomes:
        r = o.market_regime or 'unknown'
        if r not in regime_stats:
            regime_stats[r] = {"wins": 0, "total": 0}
        regime_stats[r]["total"] += 1
        if str(o.outcome).endswith('correct'):
            regime_stats[r]["wins"] += 1
    bad_regimes = [r for r, s in regime_stats.items() if s["total"] >= 3 and s["wins"] / s["total"] < 0.30]
    if bad_regimes:
        reasoning.append(f"Poor regimes (WR<30%): {', '.join(bad_regimes)}")

    confidence = min(n / 50, 1.0) * (0.8 if changes else 0.5)
    return TuningResult(
        sufficient_data=True, sample_count=n,
        current_params=current, suggested_params=suggested,
        changes=changes, reasoning=reasoning, confidence=round(confidence, 2),
    )


async def apply_suggestions(suggested: dict) -> dict:
    import services.wallet.risk_manager as rm
    applied = {}
    for key, value in suggested.items():
        if hasattr(rm, key):
            old = getattr(rm, key)
            if old != value:
                setattr(rm, key, value)
                applied[key] = {"old": old, "new": value}
    return applied
