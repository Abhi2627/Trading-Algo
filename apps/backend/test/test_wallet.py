# test/test_wallet.py — Phase 6 wallet and risk manager tests
# No DB, no network — pure logic tests.
import pytest
from services.wallet.risk_manager import RiskManager, RiskDecision
from core.models import RiskMode


@pytest.fixture
def rm():
    return RiskManager()


def _decision(rm, **kwargs) -> RiskDecision:
    """Helper: call rm.check with sensible defaults, override with kwargs."""
    defaults = dict(
        total_equity=10000.0,
        cash_balance=10000.0,
        current_price=500.0,
        confidence=0.70,
        risk_mode=RiskMode.normal,
        daily_loss_used=0.0,
        daily_loss_limit=200.0,
        is_intraday=False,
        existing_open_trades=0,
    )
    defaults.update(kwargs)
    return rm.check(**defaults)


# ---------------------------------------------------------------------------
# Approval tests
# ---------------------------------------------------------------------------

def test_valid_trade_approved(rm):
    """Standard trade with good parameters must be approved."""
    d = _decision(rm)
    assert d.approved is True
    assert d.quantity >= 1
    assert d.stop_loss < 500.0
    assert d.take_profit > 500.0


def test_halted_mode_rejects(rm):
    """Halted risk mode must reject all trades."""
    d = _decision(rm, risk_mode=RiskMode.halted)
    assert d.approved is False
    assert "halted" in d.reason.lower()


def test_low_confidence_rejects(rm):
    """Confidence below MIN_CONFIDENCE must be rejected."""
    d = _decision(rm, confidence=0.20)
    assert d.approved is False
    assert "confidence" in d.reason.lower()


def test_daily_loss_limit_rejects(rm):
    """Trade must be rejected when daily loss limit is fully used."""
    d = _decision(rm, daily_loss_used=200.0, daily_loss_limit=200.0)
    assert d.approved is False
    assert "daily loss" in d.reason.lower()


def test_max_open_trades_rejects(rm):
    """8 open trades must block new entries."""
    d = _decision(rm, existing_open_trades=8)
    assert d.approved is False
    assert "concurrent" in d.reason.lower()


def test_price_too_high_for_position_rejects(rm):
    """If position size can't buy even 1 share, must reject."""
    # price=50000, equity=1000 -> position_size ~70 < 50000
    d = _decision(rm, total_equity=1000.0, cash_balance=1000.0, current_price=50000.0)
    assert d.approved is False


# ---------------------------------------------------------------------------
# Position sizing tests
# ---------------------------------------------------------------------------

def test_quantity_is_whole_number(rm):
    """quantity must always be an integer >= 1."""
    d = _decision(rm)
    assert isinstance(d.quantity, int)
    assert d.quantity >= 1


def test_position_size_within_cash(rm):
    """Position size must never exceed available cash."""
    d = _decision(rm, cash_balance=5000.0)
    assert d.position_size <= 5000.0 * 0.95


def test_conservative_mode_halves_position(rm):
    """Conservative mode must produce smaller position than normal."""
    normal_d      = _decision(rm, risk_mode=RiskMode.normal)
    conservative_d = _decision(rm, risk_mode=RiskMode.conservative)
    assert conservative_d.position_size < normal_d.position_size


def test_high_confidence_larger_than_low(rm):
    """Higher confidence must produce a larger position size."""
    low_d  = _decision(rm, confidence=0.45)
    high_d = _decision(rm, confidence=0.90)
    assert high_d.position_size > low_d.position_size


# ---------------------------------------------------------------------------
# Stop loss / take profit tests
# ---------------------------------------------------------------------------

def test_stop_loss_below_entry(rm):
    """Stop loss must always be below entry price."""
    d = _decision(rm, current_price=1000.0)
    assert d.stop_loss < 1000.0


def test_take_profit_above_entry(rm):
    """Take profit must always be above entry price."""
    d = _decision(rm, current_price=1000.0)
    assert d.take_profit > 1000.0


def test_reward_risk_ratio_at_least_1_5(rm):
    """Reward:Risk must be >= 1.5x (take profit distance / stop distance)."""
    d = _decision(rm, current_price=1000.0)
    reward = d.take_profit - 1000.0
    risk   = 1000.0 - d.stop_loss
    assert reward / risk >= 1.5


# ---------------------------------------------------------------------------
# Daily budget tests
# ---------------------------------------------------------------------------

def test_daily_budget_scales_with_equity(rm):
    """Budget limits must scale proportionally with equity."""
    b1 = rm.check_daily_budget(10000.0)
    b2 = rm.check_daily_budget(20000.0)
    assert b2["profit_target"] == pytest.approx(b1["profit_target"] * 2)
    assert b2["loss_limit"]    == pytest.approx(b1["loss_limit"]    * 2)


def test_loss_limit_greater_than_profit_target(rm):
    """Loss limit must always be wider than profit target."""
    b = rm.check_daily_budget(10000.0)
    assert b["loss_limit"] > b["profit_target"]
