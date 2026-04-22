# services/wallet/risk_manager.py
import logging
from dataclasses import dataclass
from typing import Optional
from core.models import RiskMode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Capital tiers — system adapts strategy based on available capital
# ---------------------------------------------------------------------------
# Tier 1: ₹0    - ₹10K   — ETF-only, max 1 position, 50% position size
# Tier 2: ₹10K  - ₹50K   — Large-cap stocks + ETFs, max 3 positions
# Tier 3: ₹50K  - ₹2L    — Full Nifty 50, max 5 positions
# Tier 4: ₹2L+          — Full universe, max 8 positions

STOP_LOSS_PCT    = 0.05
TAKE_PROFIT_PCT  = 0.09
MIN_CONFIDENCE   = 0.40


def get_capital_tier(total_equity: float) -> dict:
    """Return trading parameters appropriate for the capital level."""
    if total_equity < 10_000:
        return {
            'tier':            1,
            'label':           'Micro',
            'max_positions':   1,
            'position_pct':    0.90,   # use 90% on single position
            'max_stock_price': total_equity * 0.95,  # stock must be affordable
            'etf_only':        True,   # only ETFs and cheap stocks
            'description':     'ETF-focused, single position'
        }
    elif total_equity < 50_000:
        return {
            'tier':            2,
            'label':           'Small',
            'max_positions':   3,
            'position_pct':    0.30,
            'max_stock_price': total_equity * 0.40,
            'etf_only':        False,
            'description':     'Large-cap + ETFs, up to 3 positions'
        }
    elif total_equity < 200_000:
        return {
            'tier':            3,
            'label':           'Medium',
            'max_positions':   5,
            'position_pct':    0.15,
            'max_stock_price': total_equity * 0.25,
            'etf_only':        False,
            'description':     'Full Nifty 50, up to 5 positions'
        }
    else:
        return {
            'tier':            4,
            'label':           'Standard',
            'max_positions':   8,
            'position_pct':    0.10,
            'max_stock_price': total_equity * 0.15,
            'etf_only':        False,
            'description':     'Full universe, up to 8 positions'
        }


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
    tier:           int   = 1
    suggestion:     str   = ''  # alternative if rejected


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
        Capital-adaptive position sizing.
        Adjusts max positions, position size, and stock price limits
        based on available capital.
        """
        stop_loss   = round(current_price * (1 - STOP_LOSS_PCT),   2)
        take_profit = round(current_price * (1 + TAKE_PROFIT_PCT), 2)
        tier_params = get_capital_tier(total_equity)
        tier        = tier_params['tier']

        def reject(reason: str, suggestion: str = '') -> RiskDecision:
            logger.warning(f"Trade rejected (Tier {tier}): {reason}")
            return RiskDecision(
                approved=False, reason=reason,
                position_size=0, quantity=0,
                stop_loss=stop_loss, take_profit=take_profit,
                risk_per_trade=0, tier=tier, suggestion=suggestion,
            )

        # Hard stops
        if risk_mode == RiskMode.halted:
            return reject("Portfolio halted — no new trades")

        if confidence < MIN_CONFIDENCE:
            return reject(f"Confidence {confidence:.0%} below minimum {MIN_CONFIDENCE:.0%}")

        if daily_loss_used >= daily_loss_limit:
            return reject(f"Daily loss limit reached: ₹{daily_loss_used:.2f} / ₹{daily_loss_limit:.2f}")

        # Capital-tier position limit
        max_pos = tier_params['max_positions']
        if existing_open_trades >= max_pos:
            return reject(
                f"Maximum positions ({max_pos}) for your capital tier reached",
                suggestion=f"Close an existing position to open a new one"
            )

        # Capital-tier stock price check
        max_price = tier_params['max_stock_price']
        if current_price > max_price:
            return reject(
                f"Stock at ₹{current_price:.2f} exceeds your capital tier limit ₹{max_price:.2f}",
                suggestion=(
                    f"With ₹{total_equity:.0f} capital, focus on stocks under ₹{max_price:.0f}. "
                    f"Consider Nifty BeES (~₹240) or cheaper large-caps."
                )
            )

        # Position sizing — adaptive
        base_pct   = tier_params['position_pct']
        conf_scale = min(confidence, 1.0)
        if risk_mode == RiskMode.conservative:
            base_pct *= 0.5

        position_size = min(
            total_equity  * base_pct * conf_scale,
            cash_balance  * 0.95,  # never use more than 95% of cash
        )

        if position_size < current_price:
            needed = current_price - cash_balance
            return reject(
                f"Need ₹{current_price:.2f} for 1 share, only ₹{position_size:.2f} available",
                suggestion=(
                    f"Add ₹{needed:.0f} more to your wallet, or look for stocks "
                    f"under ₹{int(position_size):.0f}. "
                    f"Nifty BeES trades around ₹240."
                )
            )

        quantity    = int(position_size // current_price)
        actual_size = quantity * current_price
        risk_amount = actual_size * STOP_LOSS_PCT

        logger.info(
            f"Risk approved (Tier {tier} / {tier_params['label']}): "
            f"qty={quantity} size=₹{actual_size:.2f} "
            f"stop=₹{stop_loss} target=₹{take_profit}"
        )

        return RiskDecision(
            approved=True, reason="approved",
            position_size=round(actual_size, 2),
            quantity=quantity,
            stop_loss=stop_loss, take_profit=take_profit,
            risk_per_trade=round(risk_amount, 2),
            tier=tier,
        )

    def check_daily_budget(
        self,
        total_equity:            float,
        daily_profit_target_pct: float = 0.015,
        max_daily_loss_pct:      float = 0.020,
    ) -> dict:
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
