# models/ensemble/ensemble.py
# Combines RL agent + Transformer + Sentiment into one final signal.
# This is the only file that talks to all three models.
import logging
from typing import Optional
from core.models import SignalAction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regime-aware ensemble weights
# Each regime shifts how much we trust each model.
# Must sum to 1.0 per regime.
# ---------------------------------------------------------------------------
REGIME_WEIGHTS = {
    "trending": {
        "rl":          0.35,
        "transformer": 0.45,   # forecaster is strongest in trends
        "sentiment":   0.20,
    },
    "volatile": {
        "rl":          0.45,   # RL handles chaos best
        "transformer": 0.20,
        "sentiment":   0.35,   # news drives volatile moves
    },
    "ranging": {
        "rl":          0.40,
        "transformer": 0.35,
        "sentiment":   0.25,
    },
}

# Minimum confidence to emit BUY or SELL
# Signals below this threshold become HOLD
MIN_CONFIDENCE_THRESHOLD = 0.35


class EnsembleEngine:
    """
    Combines outputs from all three models into a single actionable signal.

    Each model produces a directional score (-1 to +1).
    Scores are weighted by market regime and blended.
    Final score is thresholded into BUY / SELL / HOLD.

    Usage:
        engine = EnsembleEngine()
        signal = engine.combine(
            rl_output=...,
            transformer_output=...,
            sentiment_output=...,
            market_regime="trending",
        )
    """

    def combine(
        self,
        rl_output:          dict,
        transformer_output: dict,
        sentiment_output:   dict,
        market_regime:      str = "ranging",
    ) -> dict:
        """
        Blend model outputs into a final signal.

        Args:
            rl_output:          Output of RLAgent.predict()
            transformer_output: Output of PriceForecaster.predict()
            sentiment_output:   Output of SentimentService.analyse()
            market_regime:      "trending" | "ranging" | "volatile"

        Returns:
            {
              "action":           "buy" | "sell" | "hold"
              "confidence":       float (0–1)
              "ensemble_score":   float (-1 to +1)
              "rl_score":         float
              "transformer_score":float
              "sentiment_score":  float
              "weights":          dict
              "market_regime":    str
              "signal_action":    SignalAction enum value
            }
        """
        weights = REGIME_WEIGHTS.get(market_regime, REGIME_WEIGHTS["ranging"])

        # ——— Convert each model output to a -1..+1 directional score ———————

        # RL: action_id mapped to direction, scaled by confidence
        rl_action_id = rl_output.get("action_id", 0)
        rl_conf      = rl_output.get("confidence", 0.0)
        if rl_action_id == 1:    rl_score =  rl_conf   # BUY
        elif rl_action_id == 2:  rl_score = -rl_conf   # SELL
        else:                    rl_score =  0.0        # HOLD

        # Transformer: use 1-day predicted delta, scaled by confidence
        tf_delta = transformer_output.get("delta_1d", 0.0)
        tf_conf  = transformer_output.get("confidence", 0.0)
        # Normalise delta to -1..+1 (2% move = full score)
        tf_score = max(-1.0, min(1.0, tf_delta / 0.02)) * tf_conf

        # Sentiment: score already in -1..+1, scaled by magnitude
        sent_score = sentiment_output.get("score", 0.0)
        sent_mag   = sentiment_output.get("magnitude", 0.0)
        sent_score_weighted = sent_score * sent_mag

        # ——— Weighted blend —————————————————————————————————————
        ensemble_score = (
            weights["rl"]          * rl_score +
            weights["transformer"] * tf_score +
            weights["sentiment"]   * sent_score_weighted
        )

        # Confidence = absolute value of ensemble score (how decisive the blend is)
        confidence = min(abs(ensemble_score), 1.0)

        # ——— Threshold to final action ——————————————————————————————
        if ensemble_score >  MIN_CONFIDENCE_THRESHOLD:
            action       = "buy"
            signal_action = SignalAction.buy
        elif ensemble_score < -MIN_CONFIDENCE_THRESHOLD:
            action       = "sell"
            signal_action = SignalAction.sell
        else:
            action       = "hold"
            signal_action = SignalAction.hold

        return {
            "action":            action,
            "confidence":        round(confidence, 4),
            "ensemble_score":    round(ensemble_score, 4),
            "rl_score":          round(rl_score, 4),
            "transformer_score": round(tf_score, 4),
            "sentiment_score":   round(sent_score_weighted, 4),
            "weights":           weights,
            "market_regime":     market_regime,
            "signal_action":     signal_action,
        }

    def audit_record(self, ensemble_result: dict, rl_output: dict,
                     transformer_output: dict, sentiment_output: dict) -> dict:
        """
        Build the complete signal audit record stored in the database.
        This is what the chatbot reads to explain every decision.
        """
        return {
            "action":           ensemble_result["action"],
            "confidence":       ensemble_result["confidence"],
            "ensemble_score":   ensemble_result["ensemble_score"],
            "market_regime":    ensemble_result["market_regime"],
            "weights":          ensemble_result["weights"],

            # RL model details
            "rl_action":        rl_output.get("action"),
            "rl_confidence":    rl_output.get("confidence"),
            "rl_q_values":      rl_output.get("q_values"),

            # Transformer details
            "transformer_delta_1d":   transformer_output.get("delta_1d"),
            "transformer_delta_3d":   transformer_output.get("delta_3d"),
            "transformer_delta_5d":   transformer_output.get("delta_5d"),
            "transformer_direction":  transformer_output.get("direction"),
            "transformer_confidence": transformer_output.get("confidence"),

            # Sentiment details
            "sentiment_score":     sentiment_output.get("score"),
            "sentiment_magnitude": sentiment_output.get("magnitude"),
            "sentiment_direction": sentiment_output.get("direction"),
            "sentiment_factors":   sentiment_output.get("key_factors", []),
            "sentiment_source":    sentiment_output.get("source"),
        }


# Module-level singleton
_engine: Optional[EnsembleEngine] = None

def get_ensemble_engine() -> EnsembleEngine:
    global _engine
    if _engine is None:
        _engine = EnsembleEngine()
    return _engine
