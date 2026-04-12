# test/test_chat.py — Phase 8 chatbot tests
# No LLM calls, no DB — tests prompt building and context logic only.
import pytest
from unittest.mock import MagicMock
from services.chat.chatbot import Chatbot, SYSTEM_PROMPT


@pytest.fixture
def bot():
    return Chatbot()


# ---------------------------------------------------------------------------
# Prompt builder tests
# ---------------------------------------------------------------------------

def test_signal_prompt_contains_action(bot):
    """Signal explanation prompt must include the action and symbol."""
    context = {
        "type":    "signal_explanation",
        "symbol":  "NSE:RELIANCE",
        "name":    "Reliance Industries",
        "action":  "sell",
        "confidence": "78%",
        "market_regime": "trending",
        "rl_score": -0.62,
        "transformer_score": -0.45,
        "sentiment_score": -0.38,
        "ensemble_score": -0.49,
        "rsi_14": 71.4,
        "macd_line": -0.3,
        "adx": 28.0,
        "volume_ratio": 1.8,
        "atr_pct": 0.018,
        "news_headlines": ["Reliance faces regulatory pressure"],
        "generated_at": "2025-04-01T09:22:00",
    }
    prompt = bot._build_user_prompt("Why did you sell Reliance?", context)
    assert "SELL" in prompt
    assert "NSE:RELIANCE" in prompt
    assert "Reliance Industries" in prompt
    assert "78%" in prompt


def test_signal_prompt_includes_all_model_scores(bot):
    """Prompt must include all three model score fields for the LLM to reference."""
    context = {
        "type":   "signal_explanation",
        "symbol": "NSE:TCS",
        "name":   "TCS",
        "action": "buy",
        "confidence": "65%",
        "market_regime": "ranging",
        "rl_score": 0.55,
        "transformer_score": 0.40,
        "sentiment_score": 0.30,
        "ensemble_score": 0.44,
        "rsi_14": 48.0,
        "macd_line": 0.1,
        "adx": 18.0,
        "volume_ratio": 0.9,
        "atr_pct": 0.014,
        "news_headlines": [],
        "generated_at": "2025-04-01T09:22:00",
    }
    prompt = bot._build_user_prompt("Why buy TCS?", context)
    assert "rl_score" in prompt
    assert "transformer_score" in prompt
    assert "sentiment_score" in prompt


def test_portfolio_prompt_contains_equity(bot):
    """Portfolio prompt must surface total equity."""
    context = {
        "type":           "portfolio",
        "total_equity":   11250.0,
        "cash_balance":   7800.0,
        "realized_pnl":   450.0,
        "drawdown_pct":   3.2,
        "risk_mode":      "normal",
        "open_positions": [],
    }
    prompt = bot._build_user_prompt("How is my portfolio doing?", context)
    assert "11250" in prompt
    assert "portfolio" in prompt.lower()


def test_general_prompt_is_educational(bot):
    """General questions must return an educational prompt."""
    context = {"type": "general"}
    prompt = bot._build_user_prompt("What is RSI?", context)
    assert "educational" in prompt.lower() or "trading" in prompt.lower()
    assert "RSI" in prompt


def test_unknown_context_type_falls_back_to_general(bot):
    """Unknown context type must not raise — falls back gracefully."""
    context = {"type": "unknown_type"}
    prompt = bot._build_user_prompt("Hello", context)
    assert isinstance(prompt, str)
    assert len(prompt) > 0


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------

def test_system_prompt_forbids_financial_advice():
    """System prompt must explicitly prohibit financial advice."""
    assert "financial advice" in SYSTEM_PROMPT.lower() or "never give" in SYSTEM_PROMPT.lower()


def test_system_prompt_requires_disclaimer():
    """System prompt must require educational disclaimer in every response."""
    assert "educational" in SYSTEM_PROMPT.lower()
    assert "simulation" in SYSTEM_PROMPT.lower()


def test_system_prompt_forbids_invented_data():
    """System prompt must prohibit inventing data."""
    assert "never" in SYSTEM_PROMPT.lower()
    assert "invent" in SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# Signal context builder tests
# ---------------------------------------------------------------------------

def test_signal_context_structure(bot):
    """_build_signal_context must return all required fields."""
    signal = MagicMock()
    signal.action.value        = "buy"
    signal.confidence          = 0.72
    signal.market_regime       = "trending"
    signal.rl_score            = 0.60
    signal.transformer_score   = 0.55
    signal.sentiment_score     = 0.40
    signal.ensemble_score      = 0.52
    signal.created_at.isoformat.return_value = "2025-04-01T09:00:00"
    signal.technical_indicators = {"rsi_14": 52.0, "adx": 30.0}
    signal.sentiment_sources    = [{"headline": "TCS wins contract"}]

    asset = MagicMock()
    asset.symbol = "NSE:TCS"
    asset.name   = "Tata Consultancy Services"

    ctx = bot._build_signal_context(signal, asset)

    required_keys = [
        "type", "symbol", "name", "action", "confidence",
        "rl_score", "transformer_score", "sentiment_score", "ensemble_score",
        "rsi_14", "adx", "news_headlines",
    ]
    for key in required_keys:
        assert key in ctx, f"Missing key: {key}"

    assert ctx["type"]   == "signal_explanation"
    assert ctx["symbol"] == "NSE:TCS"
    assert ctx["action"] == "buy"


def test_signal_context_caps_headlines_at_three(bot):
    """news_headlines must be capped at 3 entries."""
    signal = MagicMock()
    signal.action.value        = "hold"
    signal.confidence          = 0.50
    signal.market_regime       = "ranging"
    signal.rl_score            = 0.0
    signal.transformer_score   = 0.0
    signal.sentiment_score     = 0.0
    signal.ensemble_score      = 0.0
    signal.created_at.isoformat.return_value = "2025-04-01T09:00:00"
    signal.technical_indicators = {}
    signal.sentiment_sources    = [
        {"headline": f"Headline {i}"} for i in range(10)
    ]

    asset = MagicMock()
    asset.symbol = "NSE:INFY"
    asset.name   = "Infosys"

    ctx = bot._build_signal_context(signal, asset)
    assert len(ctx["news_headlines"]) == 3


def test_signal_context_handles_empty_indicators(bot):
    """Context builder must not raise when technical_indicators is None."""
    signal = MagicMock()
    signal.action.value        = "hold"
    signal.confidence          = 0.50
    signal.market_regime       = "ranging"
    signal.rl_score            = 0.0
    signal.transformer_score   = 0.0
    signal.sentiment_score     = 0.0
    signal.ensemble_score      = 0.0
    signal.created_at.isoformat.return_value = "2025-04-01T09:00:00"
    signal.technical_indicators = None
    signal.sentiment_sources    = None

    asset = MagicMock()
    asset.symbol = "CRYPTO:BTC"
    asset.name   = "Bitcoin"

    ctx = bot._build_signal_context(signal, asset)
    assert ctx["rsi_14"]       is None
    assert ctx["news_headlines"] == []
