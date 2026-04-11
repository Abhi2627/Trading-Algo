# test/test_models.py — Phase 5 model inference tests
# All tests use synthetic data — no network, no GPU needed.
# Run: pytest test/test_models.py -v
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# Ensemble tests (no model files needed)
# ---------------------------------------------------------------------------

def test_ensemble_buy_signal():
    """Strong positive signals from all models must produce BUY."""
    from models.ensemble.ensemble import EnsembleEngine
    engine = EnsembleEngine()
    result = engine.combine(
        rl_output          = {"action_id": 1, "confidence": 0.85},
        transformer_output = {"delta_1d": 0.025, "confidence": 0.8},
        sentiment_output   = {"score": 0.7, "magnitude": 0.9},
        market_regime      = "trending",
    )
    assert result["action"] == "buy"
    assert result["ensemble_score"] > 0.35
    assert result["confidence"] > 0


def test_ensemble_sell_signal():
    """Strong negative signals from all models must produce SELL."""
    from models.ensemble.ensemble import EnsembleEngine
    engine = EnsembleEngine()
    result = engine.combine(
        rl_output          = {"action_id": 2, "confidence": 0.80},
        transformer_output = {"delta_1d": -0.03, "confidence": 0.75},
        sentiment_output   = {"score": -0.8, "magnitude": 0.85},
        market_regime      = "volatile",
    )
    assert result["action"] == "sell"
    assert result["ensemble_score"] < -0.35


def test_ensemble_hold_on_weak_signals():
    """Mixed weak signals must produce HOLD."""
    from models.ensemble.ensemble import EnsembleEngine
    engine = EnsembleEngine()
    result = engine.combine(
        rl_output          = {"action_id": 0, "confidence": 0.5},
        transformer_output = {"delta_1d": 0.001, "confidence": 0.2},
        sentiment_output   = {"score": 0.1, "magnitude": 0.2},
        market_regime      = "ranging",
    )
    assert result["action"] == "hold"
    assert abs(result["ensemble_score"]) < 0.35


def test_ensemble_weights_sum_to_one():
    """All regime weight sets must sum to exactly 1.0."""
    from models.ensemble.ensemble import REGIME_WEIGHTS
    for regime, weights in REGIME_WEIGHTS.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-9, f"{regime} weights sum to {total}, not 1.0"


def test_ensemble_unknown_regime_uses_ranging():
    """Unknown regime must fall back to ranging weights without error."""
    from models.ensemble.ensemble import EnsembleEngine
    engine = EnsembleEngine()
    result = engine.combine(
        rl_output          = {"action_id": 1, "confidence": 0.6},
        transformer_output = {"delta_1d": 0.01, "confidence": 0.5},
        sentiment_output   = {"score": 0.3, "magnitude": 0.5},
        market_regime      = "UNKNOWN_REGIME",
    )
    assert result["market_regime"] == "UNKNOWN_REGIME"
    assert "action" in result


def test_ensemble_audit_record_has_all_keys():
    """audit_record must contain all fields the chatbot needs."""
    from models.ensemble.ensemble import EnsembleEngine
    engine = EnsembleEngine()
    rl_out = {"action_id": 1, "confidence": 0.7, "q_values": [0.1, 0.7, 0.2]}
    tf_out = {"delta_1d": 0.018, "delta_3d": 0.025, "delta_5d": 0.03,
              "confidence": 0.6, "direction": "up"}
    sent_out = {"score": 0.5, "magnitude": 0.7, "direction": "bullish",
                "key_factors": ["strong earnings"], "source": "nim"}
    ensemble_result = engine.combine(
        rl_output=rl_out, transformer_output=tf_out,
        sentiment_output=sent_out, market_regime="trending",
    )
    audit = engine.audit_record(ensemble_result, rl_out, tf_out, sent_out)
    required_keys = [
        "action", "confidence", "ensemble_score", "market_regime", "weights",
        "rl_action", "rl_confidence", "rl_q_values",
        "transformer_delta_1d", "transformer_delta_3d", "transformer_direction",
        "sentiment_score", "sentiment_magnitude", "sentiment_factors", "sentiment_source",
    ]
    for key in required_keys:
        assert key in audit, f"Missing audit key: {key}"


def test_ensemble_confidence_never_exceeds_one():
    """Confidence must always be clamped to 1.0 max."""
    from models.ensemble.ensemble import EnsembleEngine
    engine = EnsembleEngine()
    result = engine.combine(
        rl_output          = {"action_id": 1, "confidence": 1.0},
        transformer_output = {"delta_1d": 0.10, "confidence": 1.0},
        sentiment_output   = {"score": 1.0, "magnitude": 1.0},
        market_regime      = "trending",
    )
    assert result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Sentiment JSON parser tests (no API calls)
# ---------------------------------------------------------------------------

def test_sentiment_parse_valid_json():
    """Valid JSON from LLM must parse correctly."""
    from models.sentiment.sentiment_service import SentimentService
    svc = SentimentService()
    raw = '{"score": 0.65, "magnitude": 0.8, "direction": "bullish", "key_factors": ["strong Q3"], "time_horizon": "short_term"}'
    result = svc._parse_json(raw)
    assert result is not None
    assert result["score"]     == pytest.approx(0.65)
    assert result["magnitude"] == pytest.approx(0.8)
    assert result["direction"] == "bullish"


def test_sentiment_parse_markdown_fences():
    """LLM sometimes wraps JSON in markdown — must strip cleanly."""
    from models.sentiment.sentiment_service import SentimentService
    svc = SentimentService()
    raw = '```json\n{"score": -0.4, "magnitude": 0.6, "direction": "bearish", "key_factors": [], "time_horizon": "immediate"}\n```'
    result = svc._parse_json(raw)
    assert result is not None
    assert result["score"] == pytest.approx(-0.4)


def test_sentiment_score_clamped():
    """Scores outside -1..+1 must be clamped, not rejected."""
    from models.sentiment.sentiment_service import SentimentService
    svc = SentimentService()
    raw = '{"score": 5.0, "magnitude": -2.0, "direction": "bullish", "key_factors": [], "time_horizon": "short_term"}'
    result = svc._parse_json(raw)
    assert result is not None
    assert result["score"]     == pytest.approx(1.0)
    assert result["magnitude"] == pytest.approx(0.0)


def test_sentiment_invalid_json_returns_none():
    """Unparseable LLM output must return None gracefully."""
    from models.sentiment.sentiment_service import SentimentService
    svc = SentimentService()
    result = svc._parse_json("This is not JSON at all.")
    assert result is None


# ---------------------------------------------------------------------------
# RL agent fallback (model file may or may not exist)
# ---------------------------------------------------------------------------

def test_rl_agent_fallback_structure():
    """_fallback() must always return a valid HOLD response."""
    from models.rl.agent import RLAgent
    agent = RLAgent.__new__(RLAgent)
    agent.is_ready      = False
    agent._model        = None
    agent._vec_norm     = None
    agent._feature_cols = None
    result = agent._fallback("model not loaded")
    assert result["action"]     == "hold"
    assert result["action_id"]  == 0
    assert result["confidence"] == 0.0
    assert "error" in result


# ---------------------------------------------------------------------------
# Transformer fallback
# ---------------------------------------------------------------------------

def test_transformer_fallback_structure():
    """_fallback() must always return a valid sideways response."""
    from models.transformer.forecaster import PriceForecaster
    fc = PriceForecaster.__new__(PriceForecaster)
    fc.is_ready = False
    result = fc._fallback("model not loaded")
    assert result["direction"]  == "sideways"
    assert result["confidence"] == 0.0
    assert result["delta_1d"]   == 0.0
    assert "error" in result
