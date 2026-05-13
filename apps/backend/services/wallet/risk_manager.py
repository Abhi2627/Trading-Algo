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

STOP_LOSS_PCT    = 0.03   # Fallback fixed SL — used when ATR fetch fails
TAKE_PROFIT_PCT  = 0.08   # Fallback fixed TP — used when ATR fetch fails
MIN_CONFIDENCE   = 0.60   # Only quality signals
TIME_EXIT_DAYS   = 3      # Exit after 3 days if not profitable

# ATR-based SL/TP multipliers
# SL = entry - ATR_SL_MULT * ATR(14)   → 2x ATR below entry
# TP = entry + ATR_TP_MULT * ATR(14)   → 4x ATR above entry (2:1 RR)
ATR_SL_MULT      = 2.0
ATR_TP_MULT      = 4.0
ATR_PERIOD       = 14

# Hard caps: ATR-derived SL/TP must stay within these bands
# Prevents absurd stops on illiquid stocks with huge ATR
ATR_SL_MIN_PCT   = 0.015  # SL never tighter than 1.5% (noise)
ATR_SL_MAX_PCT   = 0.07   # SL never wider than 7% (too much risk)
ATR_TP_MIN_PCT   = 0.04   # TP never less than 4%
ATR_TP_MAX_PCT   = 0.20   # TP never more than 20%


def compute_atr_stops(
    symbol: str,
    entry_price: float,
) -> tuple[float, float, str]:
    """
    Compute ATR(14)-based stop-loss and take-profit prices.

    Returns:
        (stop_loss, take_profit, method)
        method is 'atr' if ATR was used, 'fixed' if fallback.
    """
    try:
        from services.market_data.fetcher import fetch_historical
        import pandas as pd

        # Need at least ATR_PERIOD + 1 rows — fetch 60 days to be safe
        df = fetch_historical(symbol, period_days=60, interval='1d')
        if df is None or len(df) < ATR_PERIOD + 1:
            raise ValueError(f"Insufficient history: {len(df) if df is not None else 0} rows")

        # True Range = max(H-L, |H-Cprev|, |L-Cprev|)
        df = df.tail(ATR_PERIOD + 5).copy()  # only need last few rows
        df['prev_close'] = df['close'].shift(1)
        df['tr'] = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['prev_close']).abs(),
            (df['low']  - df['prev_close']).abs(),
        ], axis=1).max(axis=1)
        atr = df['tr'].dropna().tail(ATR_PERIOD).mean()

        if atr <= 0 or pd.isna(atr):
            raise ValueError(f"Invalid ATR: {atr}")

        raw_sl = entry_price - ATR_SL_MULT * atr
        raw_tp = entry_price + ATR_TP_MULT * atr

        # Clamp to hard-cap bands
        sl_pct = (entry_price - raw_sl) / entry_price
        tp_pct = (raw_tp - entry_price) / entry_price

        sl_pct = max(ATR_SL_MIN_PCT, min(sl_pct, ATR_SL_MAX_PCT))
        tp_pct = max(ATR_TP_MIN_PCT, min(tp_pct, ATR_TP_MAX_PCT))

        stop_loss   = round(entry_price * (1 - sl_pct), 2)
        take_profit = round(entry_price * (1 + tp_pct), 2)

        logger.info(
            f"ATR stops for {symbol}: ATR={atr:.2f} "
            f"SL=₹{stop_loss} ({sl_pct:.1%}) "
            f"TP=₹{take_profit} ({tp_pct:.1%})"
        )
        return stop_loss, take_profit, 'atr'

    except Exception as e:
        logger.warning(f"ATR computation failed for {symbol}: {e} — using fixed fallback")
        stop_loss   = round(entry_price * (1 - STOP_LOSS_PCT),   2)
        take_profit = round(entry_price * (1 + TAKE_PROFIT_PCT), 2)
        return stop_loss, take_profit, 'fixed'


# ---------------------------------------------------------------------------
# Sector map — derived from SECTIONS in assets.py
# Used for concentration checks: don't hold >MAX_SAME_SECTOR stocks
# ---------------------------------------------------------------------------

MAX_SAME_SECTOR = 2   # max positions in any one sector simultaneously

# Build symbol → sector mapping at import time (zero runtime cost)
_SECTOR_MAP: dict[str, str] = {}

def _build_sector_map() -> dict[str, str]:
    from services.market_data.assets import SECTIONS
    mapping = {}
    for section_id, _, symbols in SECTIONS:
        for sym, _ in symbols:
            # Use the base ticker without exchange prefix for matching
            # so NSE:TCS and BSE:TCS both map to 'nifty_it'
            ticker = sym.split(":", 1)[1]
            # First section wins (avoids Nifty 50 overriding sector-specific)
            if ticker not in mapping:
                mapping[ticker] = section_id
    return mapping


def get_sector(symbol: str) -> str:
    """
    Return the sector/index section for a symbol.
    e.g. 'NSE:TCS' → 'nifty_it', 'NSE:HDFCBANK' → 'nifty_bank'
    Returns 'unknown' if not found.
    """
    global _SECTOR_MAP
    if not _SECTOR_MAP:
        _SECTOR_MAP = _build_sector_map()
    ticker = symbol.split(":", 1)[1] if ":" in symbol else symbol
    return _SECTOR_MAP.get(ticker, 'unknown')


def check_sector_concentration(
    symbol: str,
    open_trade_symbols: list[str],
) -> tuple[bool, str]:
    """
    Check if opening this symbol would breach sector concentration limit.

    Returns:
        (ok, reason) — ok=True means safe to proceed
    """
    sector = get_sector(symbol)
    if sector == 'unknown':
        return True, ''   # unknown sector — don't block

    same_sector = [
        s for s in open_trade_symbols
        if get_sector(s) == sector and s != symbol
    ]
    if len(same_sector) >= MAX_SAME_SECTOR:
        return False, (
            f"Sector concentration: already holding {len(same_sector)} "
            f"{sector.replace('_', ' ').title()} stock(s) "
            f"({', '.join(same_sector)}). Max {MAX_SAME_SECTOR} per sector."
        )
    return True, ''


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
    suggestion:     str   = ''
    sl_method:      str   = 'fixed'  # 'atr' or 'fixed'


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
        symbol:               str  = '',
        open_trade_symbols:   list = None,  # for sector concentration check
    ) -> RiskDecision:
        """
        Capital-adaptive position sizing with ATR-based stop-loss.
        Falls back to fixed SL/TP if ATR fetch fails.
        """
        tier_params = get_capital_tier(total_equity)
        tier        = tier_params['tier']

        # Compute ATR-based stops upfront (or fall back to fixed)
        if symbol:
            stop_loss, take_profit, sl_method = compute_atr_stops(symbol, current_price)
        else:
            stop_loss   = round(current_price * (1 - STOP_LOSS_PCT),   2)
            take_profit = round(current_price * (1 + TAKE_PROFIT_PCT), 2)
            sl_method   = 'fixed'

        def reject(reason: str, suggestion: str = '') -> RiskDecision:
            logger.warning(f"Trade rejected (Tier {tier}): {reason}")
            return RiskDecision(
                approved=False, reason=reason,
                position_size=0, quantity=0,
                stop_loss=stop_loss, take_profit=take_profit,
                risk_per_trade=0, tier=tier, suggestion=suggestion,
                sl_method=sl_method,
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

        # Sector concentration check
        if symbol and open_trade_symbols:
            ok, reason = check_sector_concentration(symbol, open_trade_symbols)
            if not ok:
                return reject(reason, suggestion="Diversify across sectors for better risk management")

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

        # Position sizing — confidence weighted
        # Higher confidence → bigger position (40/35/25% split for Tier 2+)
        base_pct   = tier_params['position_pct']
        # Scale position size by confidence: 60% conf = 0.75x, 80% conf = 1.0x, 95% conf = 1.2x
        conf_scale = 0.5 + (min(confidence, 1.0) * 0.75)
        if risk_mode == RiskMode.conservative:
            conf_scale *= 0.5

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
            f"stop=₹{stop_loss} ({sl_method}) target=₹{take_profit}"
        )

        return RiskDecision(
            approved=True, reason="approved",
            position_size=round(actual_size, 2),
            quantity=quantity,
            stop_loss=stop_loss, take_profit=take_profit,
            risk_per_trade=round(risk_amount, 2),
            tier=tier,
            sl_method=sl_method,
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
