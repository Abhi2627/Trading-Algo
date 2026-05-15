# services/wallet/kelly.py
# Kelly Criterion position sizing for AlgoTrade.
#
# Kelly formula: f* = (p*b - q) / b
#   f* = fraction of capital to bet
#   p  = probability of winning (signal confidence)
#   q  = probability of losing (1 - p)
#   b  = win/loss ratio (expected gain / expected loss = TP_pct / SL_pct)
#
# We use FRACTIONAL Kelly (half-Kelly) to be conservative:
#   - Full Kelly is mathematically optimal but has massive drawdowns in practice
#   - Half-Kelly gives ~75% of the return with ~50% of the volatility
#   - Jane Street, Renaissance all use fractional Kelly
#
# Portfolio heat: total % of capital currently at risk across ALL open positions.
#   - Each open position contributes: (position_size / equity) * sl_pct
#   - Total heat capped at MAX_PORTFOLIO_HEAT (20%) to prevent correlated blowup
#
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Kelly parameters
KELLY_FRACTION   = 0.5    # Half-Kelly — conservative, proven to work
KELLY_MIN_PCT    = 0.05   # Never bet less than 5% of capital (too small to matter)
KELLY_MAX_PCT    = 0.40   # Never bet more than 40% of capital (concentration risk)

# Portfolio heat parameters
MAX_PORTFOLIO_HEAT = 0.20  # Max 20% of total equity at risk at any time
                           # At SL=3%, this means max ~6.67 full positions

# Minimum edge required to trade
# If Kelly fraction < this, the signal has negative or near-zero edge
MIN_KELLY_EDGE   = 0.02   # 2% minimum Kelly fraction


@dataclass
class KellyResult:
    """Output of Kelly position sizing calculation."""
    fraction:        float   # raw Kelly fraction (0-1)
    half_kelly:      float   # fractional Kelly applied
    position_pct:    float   # final position size as % of equity (after all caps)
    position_size:   float   # position size in ₹
    quantity:        int     # number of shares
    has_edge:        bool    # True if Kelly fraction > MIN_KELLY_EDGE
    portfolio_heat:  float   # current portfolio heat before this trade
    heat_after:      float   # portfolio heat after adding this trade
    heat_blocked:    bool    # True if heat limit would be breached
    reason:          str     # human-readable explanation


def compute_kelly(
    confidence:       float,   # signal confidence (0-1), used as win probability
    stop_loss_pct:    float,   # distance to SL as decimal (e.g. 0.03 for 3%)
    take_profit_pct:  float,   # distance to TP as decimal (e.g. 0.08 for 8%)
    total_equity:     float,   # total portfolio equity
    cash_balance:     float,   # available cash
    current_price:    float,   # stock price
    open_positions:   list,    # list of dicts with 'position_size', 'sl_pct', 'equity_at_entry'
    max_position_pct: float = KELLY_MAX_PCT,  # tier-based hard cap
) -> KellyResult:
    """
    Compute Kelly-optimal position size for a trade.

    Args:
        confidence:      Model confidence as win probability
        stop_loss_pct:   SL distance (e.g. 0.03 = 3% stop)
        take_profit_pct: TP distance (e.g. 0.08 = 8% target)
        total_equity:    Total portfolio value
        cash_balance:    Available cash to deploy
        current_price:   Entry price per share
        open_positions:  List of current open positions for heat calculation
        max_position_pct: Hard cap from capital tier

    Returns:
        KellyResult with position size and diagnostics
    """
    # 1. Compute raw Kelly fraction
    p = confidence          # win probability
    q = 1.0 - confidence   # loss probability
    b = take_profit_pct / stop_loss_pct  # win/loss ratio (reward:risk)

    # Kelly formula
    raw_kelly = (p * b - q) / b

    # 2. Apply half-Kelly
    half_k = raw_kelly * KELLY_FRACTION

    # 3. Check if there's any edge
    has_edge = raw_kelly >= MIN_KELLY_EDGE

    if not has_edge:
        return KellyResult(
            fraction=raw_kelly, half_kelly=half_k,
            position_pct=0, position_size=0, quantity=0,
            has_edge=False, portfolio_heat=0, heat_after=0, heat_blocked=False,
            reason=(
                f"No edge: Kelly={raw_kelly:.1%} < min {MIN_KELLY_EDGE:.1%}. "
                f"Signal conf={confidence:.0%}, RR={b:.2f}:1"
            )
        )

    # 4. Clamp to min/max bands
    clamped = max(KELLY_MIN_PCT, min(half_k, max_position_pct))

    # 5. Portfolio heat check
    current_heat = _compute_portfolio_heat(open_positions, total_equity)
    this_heat    = clamped * stop_loss_pct  # risk contribution of this position

    heat_after   = current_heat + this_heat
    heat_blocked = heat_after > MAX_PORTFOLIO_HEAT

    if heat_blocked:
        # Reduce position size to fit within heat budget
        remaining_heat  = MAX_PORTFOLIO_HEAT - current_heat
        if remaining_heat <= 0:
            return KellyResult(
                fraction=raw_kelly, half_kelly=half_k,
                position_pct=0, position_size=0, quantity=0,
                has_edge=True, portfolio_heat=current_heat,
                heat_after=current_heat, heat_blocked=True,
                reason=(
                    f"Portfolio heat at {current_heat:.1%} — "
                    f"no room for new positions (max {MAX_PORTFOLIO_HEAT:.0%})"
                )
            )
        # Scale down to fit heat budget
        clamped   = remaining_heat / stop_loss_pct
        clamped   = max(KELLY_MIN_PCT, min(clamped, max_position_pct))
        heat_after = current_heat + clamped * stop_loss_pct
        heat_blocked = False  # we fit it in at reduced size

    # 6. Compute ₹ position size
    raw_size   = total_equity * clamped
    position_size = min(raw_size, cash_balance * 0.95)

    if position_size < current_price:
        return KellyResult(
            fraction=raw_kelly, half_kelly=half_k,
            position_pct=clamped, position_size=0, quantity=0,
            has_edge=True, portfolio_heat=current_heat,
            heat_after=current_heat, heat_blocked=False,
            reason=f"Position size ₹{position_size:.0f} < stock price ₹{current_price:.0f}"
        )

    quantity = int(position_size // current_price)
    actual_size = quantity * current_price

    logger.info(
        f"Kelly sizing: raw={raw_kelly:.1%} half={half_k:.1%} "
        f"clamped={clamped:.1%} size=₹{actual_size:.0f} qty={quantity} "
        f"heat={current_heat:.1%}→{heat_after:.1%} "
        f"(conf={confidence:.0%} RR={b:.2f}:1 SL={stop_loss_pct:.1%})"
    )

    return KellyResult(
        fraction=raw_kelly,
        half_kelly=half_k,
        position_pct=clamped,
        position_size=round(actual_size, 2),
        quantity=quantity,
        has_edge=True,
        portfolio_heat=current_heat,
        heat_after=heat_after,
        heat_blocked=False,
        reason=(
            f"Kelly={raw_kelly:.1%} → Half-Kelly={half_k:.1%} → "
            f"Final={clamped:.1%} (heat {current_heat:.1%}→{heat_after:.1%})"
        )
    )


def _compute_portfolio_heat(open_positions: list, total_equity: float) -> float:
    """
    Compute current portfolio heat = sum of (position_size/equity * sl_pct)
    across all open positions.

    Each open position dict should have:
        - 'position_size': ₹ invested
        - 'sl_pct': stop-loss distance as decimal
    """
    if not open_positions or total_equity <= 0:
        return 0.0

    total_heat = 0.0
    for pos in open_positions:
        size   = pos.get('position_size', 0) or 0
        sl_pct = pos.get('sl_pct', KELLY_MIN_PCT) or KELLY_MIN_PCT
        heat   = (size / total_equity) * sl_pct
        total_heat += heat

    return round(total_heat, 4)


def kelly_summary(result: KellyResult) -> str:
    """Human-readable summary of Kelly calculation for logging."""
    if not result.has_edge:
        return f"NO EDGE — {result.reason}"
    if result.heat_blocked:
        return f"HEAT BLOCKED — {result.reason}"
    return (
        f"KELLY: {result.fraction:.1%} raw → {result.position_pct:.1%} final "
        f"(₹{result.position_size:.0f}, {result.quantity} shares) "
        f"heat: {result.portfolio_heat:.1%}→{result.heat_after:.1%}"
    )
