# services/wallet/risk_manager.py
import logging
from dataclasses import dataclass
from typing import Optional
from core.models import RiskMode

logger = logging.getLogger(__name__)

MAX_POSITION_PCT     = 0.10
MIN_CONFIDENCE       = 0.40
STOP_LOSS_PCT        = 0.05
TAKE_PROFIT_PCT      = 0.09
INTRADAY_ALLOC_PCT   = 0.25
POSITIONAL_ALLOC_PCT = 0.75


@dataclass
class RiskDecision:
    """Result of a pre-trade risk check."""
    approved:       bool
    reason:         str
    position_size:  float
    quantity:       int
    stop_loss:      float
    take_profit:    float
    risk_per_trade: float


class RiskManager:
    """Enforces position sizing and pre-trade risk rules."""

    def check(
        self,
        total_equity:         float,
        cash_balance:         float,
        current_price:        float,
        confidence:           float,
        risk_mode:            RiskMode,
        daily_loss_used:      float,
        daily_loss_limit:     float,
        is_intraday:          bool = False,
        existing_open_trades: int  = 0,
    ) -> RiskDecision:
        """
        Compute price levels first, then run approval checks.
        stop_loss and take_profit are always populated regardless of outcome.
        """
        # Always compute price levels — independent of approval
        stop_loss   = round(current_price * (1 - STOP_LOSS_PCT),   2)
        take_profit = round(current_price * (1 + TAKE_PROFIT_PCT), 2)

        def reject(reason: str) -> RiskDecision:
            logger.warning(f"Trade rejected: {reason}")
            return RiskDecision(
                approved=False, reason=reason,
                position_size=0, quantity=0,
                stop_loss=stop_loss, take_profit=take_profit,
                risk_per_trade=0,
            )

        # Approval checks
        if risk_mode == RiskMode.halted:
            return reject("Portfolio in halted mode — no new trades")

        if confidence < MIN_CONFIDENCE:
            return reject(
                f"Signal confidence {confidence:.0%} below minimum {MIN_CONFIDENCE:.0%}"
            )

        if daily_loss_used >= daily_loss_limit:
            return reject(
                f"Daily loss limit reached: ₹{daily_loss_used:.2f} / ₹{daily_loss_limit:.2f}"
            )

        if existing_open_trades >= 8:
            return reject("Maximum concurrent positions (8) reached")

        # Position sizing
        bucket   = total_equity * (INTRADAY_ALLOC_PCT if is_intraday else POSITIONAL_ALLOC_PCT)
        size_pct = MAX_POSITION_PCT * (0.5 if risk_mode == RiskMode.conservative else 1.0)
        size_pct *= min(confidence, 1.0)

        position_size = min(
            total_equity * size_pct,
            bucket * 0.5,
            cash_balance * 0.95,
        )

        if position_size < current_price:
            return reject(
                f"Position size ₹{position_size:.2f} too small to buy "
                f"even 1 share at ₹{current_price:.2f}"
            )

        quantity    = int(position_size // current_price)
        actual_size = quantity * current_price
        risk_amount = actual_size * STOP_LOSS_PCT

        logger.info(
            f"Risk approved: qty={quantity} size=₹{actual_size:.2f} "
            f"stop=₹{stop_loss} target=₹{take_profit}"
        )

        return RiskDecision(
            approved=True,
            reason="approved",
            position_size=round(actual_size, 2),
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_per_trade=round(risk_amount, 2),
        )

    def check_daily_budget(
        self,
        total_equity:            float,
        daily_profit_target_pct: float = 0.015,
        max_daily_loss_pct:      float = 0.020,
    ) -> dict:
        """Return daily budget limits in rupees."""
        return {
            "profit_target": round(total_equity * daily_profit_target_pct, 2),
            "loss_limit":    round(total_equity * max_daily_loss_pct,      2),
        }


_manager: Optional[RiskManager] = None

def get_risk_manager() -> RiskManager:
    global _manager
    if _manager is None:
        _manager = RiskManager()
    return _manager
