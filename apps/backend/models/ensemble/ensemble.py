# models/ensemble/ensemble.py
import logging
from typing import Optional
from core.models import SignalAction

logger = logging.getLogger(__name__)

MIN_CONFIDENCE_THRESHOLD = 0.35

REGIME_WEIGHTS = {
    "trending": {"rl": 0.70, "transformer": 0.10, "sentiment": 0.20},
    "volatile": {"rl": 0.55, "transformer": 0.10, "sentiment": 0.35},
    "ranging":  {"rl": 0.65, "transformer": 0.10, "sentiment": 0.25},
}


class EnsembleEngine:
    """
    Combines RL + Transformer + Sentiment into one signal.
    Weights are decided dynamically by the Meta-Agent (Ollama).
    Falls back to static regime weights if Meta-Agent unavailable.
    """

    def combine(
        self,
        rl_output:          dict,
        transformer_output: dict,
        sentiment_output:   dict,
        market_regime:      str = "ranging",
        weights:            Optional[dict] = None,
    ) -> dict:
        # Use Meta-Agent weights if provided, else static fallback
        w = weights or REGIME_WEIGHTS.get(market_regime, REGIME_WEIGHTS["ranging"])

        # RL score
        rl_action_id = rl_output.get("action_id", 0)
        rl_conf      = rl_output.get("confidence", 0.0)
        if rl_action_id == 1:   rl_score =  rl_conf
        elif rl_action_id == 2: rl_score = -rl_conf
        else:                   rl_score =  0.0

        # Transformer score
        tf_delta = transformer_output.get("delta_1d", 0.0)
        tf_conf  = transformer_output.get("confidence", 0.0)
        tf_score = max(-1.0, min(1.0, tf_delta / 0.02)) * tf_conf

        # Sentiment score
        sent_score = sentiment_output.get("score", 0.0)
        sent_mag   = sentiment_output.get("magnitude", 0.0)
        sent_weighted = sent_score * sent_mag

        # Weighted blend
        ensemble_score = (
            w["rl"]          * rl_score +
            w["transformer"] * tf_score +
            w["sentiment"]   * sent_weighted
        )

        confidence = min(abs(ensemble_score), 1.0)

        if ensemble_score > MIN_CONFIDENCE_THRESHOLD:
            action, signal_action = "buy",  SignalAction.buy
        elif ensemble_score < -MIN_CONFIDENCE_THRESHOLD:
            action, signal_action = "sell", SignalAction.sell
        else:
            action, signal_action = "hold", SignalAction.hold

        return {
            "action":            action,
            "confidence":        round(confidence, 4),
            "ensemble_score":    round(ensemble_score, 4),
            "rl_score":          round(rl_score, 4),
            "transformer_score": round(tf_score, 4),
            "sentiment_score":   round(sent_weighted, 4),
            "weights":           w,
            "weights_source":    w.get("source", "static"),
            "market_regime":     market_regime,
            "signal_action":     signal_action,
        }

    def audit_record(self, ensemble_result, rl_output, transformer_output, sentiment_output):
        return {
            "action":           ensemble_result["action"],
            "confidence":       ensemble_result["confidence"],
            "ensemble_score":   ensemble_result["ensemble_score"],
            "market_regime":    ensemble_result["market_regime"],
            "weights":          ensemble_result["weights"],
            "weights_source":   ensemble_result.get("weights_source", "static"),
            "rl_action":            rl_output.get("action"),
            "rl_confidence":        rl_output.get("confidence"),
            "rl_q_values":          rl_output.get("q_values"),
            "transformer_delta_1d":   transformer_output.get("delta_1d"),
            "transformer_delta_3d":   transformer_output.get("delta_3d"),
            "transformer_delta_5d":   transformer_output.get("delta_5d"),
            "transformer_direction":  transformer_output.get("direction"),
            "transformer_confidence": transformer_output.get("confidence"),
            "sentiment_score":     sentiment_output.get("score"),
            "sentiment_magnitude": sentiment_output.get("magnitude"),
            "sentiment_direction": sentiment_output.get("direction"),
            "sentiment_factors":   sentiment_output.get("key_factors", []),
            "sentiment_source":    sentiment_output.get("source"),
        }


_engine: Optional[EnsembleEngine] = None

def get_ensemble_engine() -> EnsembleEngine:
    global _engine
    if _engine is None:
        _engine = EnsembleEngine()
    return _engine
