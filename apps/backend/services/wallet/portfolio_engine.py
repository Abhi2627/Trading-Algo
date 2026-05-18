# services/wallet/portfolio_engine.py
# Dynamic portfolio construction engine.
# Replaces hardcoded tiers with mathematically optimal position sizing.
#
# Core insight (what Jane Street actually does):
#   Given N signals with confidences c_i and risk metrics, find allocations w_i
#   that maximize expected portfolio return subject to:
#     - Total portfolio risk (heat) <= MAX_HEAT
#     - No single position > MAX_SINGLE_PCT
#     - Sector concentration limits
#     - Correlation-adjusted sizing (correlated stocks share one Kelly bet)
#
# The system dynamically determines:
#   - How many positions to hold (not hardcoded)
#   - How much to allocate to each (Kelly-optimal)
#   - Which signals to include (Sharpe-ranked after correlation discount)
#
import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Portfolio-level constraints (the ONLY hardcoded limits) ─────────────────

MAX_PORTFOLIO_HEAT     = 0.20   # max 20% of equity at risk simultaneously
MAX_SINGLE_POSITION    = 0.30   # no single stock > 30% of equity (reduced from 35%)
MAX_PSU_POSITION       = 0.15   # PSU bank stocks capped at 15% due to policy risk
MAX_SECTOR_EXPOSURE    = 0.40   # no sector > 40% of equity
MIN_POSITION_SIZE_INR  = 500    # don't open positions smaller than ₹500
KELLY_FRACTION         = 0.5    # half-Kelly throughout
MIN_KELLY_EDGE         = 0.02   # reject if Kelly fraction < 2%
CORRELATION_WINDOW     = 60     # days of history for correlation calculation
HIGH_CORRELATION_THRESH = 0.70  # stocks above this share a Kelly allocation


@dataclass
class CandidateSignal:
    """A signal being considered for portfolio inclusion."""
    symbol:          str
    confidence:      float    # model confidence (win probability)
    sl_pct:          float    # stop-loss distance
    tp_pct:          float    # take-profit distance
    ensemble_score:  float    # overall signal quality score
    sector:          str      = 'unknown'
    current_price:   float    = 0.0
    kelly_fraction:  float    = 0.0   # computed by engine
    final_allocation: float   = 0.0   # final % of equity to allocate
    position_size:   float    = 0.0   # ₹ amount
    quantity:        int      = 0
    rejection_reason: str     = ''
    correlation_group: int    = -1    # signals in same group share Kelly


@dataclass
class PortfolioAllocation:
    """Output of portfolio engine — the complete trade plan."""
    candidates_in:    int                        # signals considered
    positions_out:    int                        # positions to open
    allocations:      list[CandidateSignal]      # approved allocations
    rejected:         list[CandidateSignal]      # rejected with reasons
    total_deployed:   float                      # ₹ to deploy
    total_heat:       float                      # portfolio risk after trades
    existing_heat:    float                      # risk from current open positions
    sharpe_estimate:  float                      # estimated portfolio Sharpe
    explanation:      str                        # human-readable summary


class PortfolioEngine:
    """
    Dynamic portfolio construction — no hardcoded position limits.
    Determines optimal number of positions and allocation per position
    based on capital, signal quality, and risk constraints.
    """

    def construct(
        self,
        signals:          list[CandidateSignal],   # candidate BUY signals today
        total_equity:     float,                    # total portfolio value
        cash_balance:     float,                    # available cash
        open_positions:   list[dict],               # current open positions
        fetch_history_fn  = None,                   # optional: fn(symbol) -> pd.DataFrame
    ) -> PortfolioAllocation:
        """
        Main entry point. Given candidate signals and portfolio state,
        returns optimal allocation plan.
        """
        if not signals:
            return PortfolioAllocation(
                candidates_in=0, positions_out=0,
                allocations=[], rejected=[],
                total_deployed=0, total_heat=0,
                existing_heat=0, sharpe_estimate=0,
                explanation="No candidate signals"
            )

        # 1. Compute existing portfolio heat
        existing_heat = self._compute_heat(open_positions, total_equity)
        heat_budget   = MAX_PORTFOLIO_HEAT - existing_heat

        if heat_budget <= 0:
            return PortfolioAllocation(
                candidates_in=len(signals), positions_out=0,
                allocations=[], rejected=signals,
                total_deployed=0, total_heat=existing_heat,
                existing_heat=existing_heat, sharpe_estimate=0,
                explanation=f"Portfolio heat {existing_heat:.1%} at max {MAX_PORTFOLIO_HEAT:.0%} — no new positions"
            )

        # 2. Compute Kelly fraction for each signal
        for sig in signals:
            sig.kelly_fraction = self._kelly(sig.confidence, sig.sl_pct, sig.tp_pct)

        # 3. Compute pairwise correlations and group correlated signals
        if fetch_history_fn and len(signals) > 1:
            groups = self._group_by_correlation(signals, fetch_history_fn)
        else:
            groups = {i: [sig] for i, sig in enumerate(signals)}

        # 4. For each correlation group, keep only the best signal
        # (correlated stocks should not get independent Kelly allocations)
        deduped_signals = []
        for group_id, group_signals in groups.items():
            # Sort by Kelly fraction × ensemble_score — best signal in group wins
            best = max(group_signals, key=lambda s: s.kelly_fraction * s.ensemble_score)
            best.correlation_group = group_id
            # If group has multiple signals, discount Kelly proportionally
            if len(group_signals) > 1:
                # Split the group's Kelly allocation across members
                for s in group_signals:
                    s.kelly_fraction *= (1 / len(group_signals))
                    s.correlation_group = group_id
                deduped_signals.extend(group_signals)
                logger.info(
                    f"Correlation group {group_id}: {[s.symbol for s in group_signals]} "
                    f"Kelly split {best.kelly_fraction:.1%} each"
                )
            else:
                deduped_signals.append(best)

        # 5. Rank signals by risk-adjusted score: Kelly × confidence / sl_pct
        # This is the Sharpe-proxy — reward per unit of risk
        deduped_signals.sort(
            key=lambda s: (s.kelly_fraction * s.confidence / max(s.sl_pct, 0.01)),
            reverse=True
        )

        # 6. Greedily allocate capital respecting all constraints
        approved      = []
        rejected_sigs = []
        remaining_heat  = heat_budget
        remaining_cash  = cash_balance
        sector_exposure: dict[str, float] = {}

        for sig in deduped_signals:
            # Skip signals with no edge
            if sig.kelly_fraction < MIN_KELLY_EDGE:
                sig.rejection_reason = f"No edge: Kelly={sig.kelly_fraction:.1%} < {MIN_KELLY_EDGE:.1%}"
                rejected_sigs.append(sig)
                continue

            # Compute this position's allocation
            # PSU banks get a tighter cap due to policy/volatility risk
            from services.wallet.risk_manager import _PSU_BANKS
            ticker = sig.symbol.split(':')[-1].upper()
            single_cap = MAX_PSU_POSITION if ticker in _PSU_BANKS else MAX_SINGLE_POSITION

            raw_alloc    = sig.kelly_fraction * KELLY_FRACTION
            raw_alloc    = min(raw_alloc, single_cap)
            position_inr = total_equity * raw_alloc
            position_inr = min(position_inr, remaining_cash * 0.95)

            # Check minimum size
            if position_inr < MIN_POSITION_SIZE_INR:
                sig.rejection_reason = f"Position ₹{position_inr:.0f} below minimum ₹{MIN_POSITION_SIZE_INR}"
                rejected_sigs.append(sig)
                continue

            # Check can afford at least 1 share
            if position_inr < sig.current_price:
                sig.rejection_reason = f"₹{position_inr:.0f} insufficient for 1 share @ ₹{sig.current_price:.0f}"
                rejected_sigs.append(sig)
                continue

            # Check heat budget
            this_heat = raw_alloc * sig.sl_pct
            if this_heat > remaining_heat:
                # Can we fit a smaller position?
                max_alloc = remaining_heat / sig.sl_pct
                if max_alloc < MIN_KELLY_EDGE:
                    sig.rejection_reason = f"Heat budget exhausted ({remaining_heat:.1%} left)"
                    rejected_sigs.append(sig)
                    continue
                raw_alloc    = max_alloc
                position_inr = total_equity * raw_alloc
                position_inr = min(position_inr, remaining_cash * 0.95)
                this_heat    = raw_alloc * sig.sl_pct

            # Check sector concentration
            current_sector_exp = sector_exposure.get(sig.sector, 0)
            if current_sector_exp + raw_alloc > MAX_SECTOR_EXPOSURE:
                max_sector_alloc = MAX_SECTOR_EXPOSURE - current_sector_exp
                if max_sector_alloc < MIN_KELLY_EDGE:
                    sig.rejection_reason = f"Sector {sig.sector} at {current_sector_exp:.0%} limit"
                    rejected_sigs.append(sig)
                    continue
                raw_alloc    = max_sector_alloc
                position_inr = total_equity * raw_alloc
                position_inr = min(position_inr, remaining_cash * 0.95)
                this_heat    = raw_alloc * sig.sl_pct

            quantity = int(position_inr // sig.current_price)
            if quantity == 0:
                sig.rejection_reason = "Rounded to 0 shares after constraints"
                rejected_sigs.append(sig)
                continue

            actual_size = quantity * sig.current_price

            # Commit allocation
            sig.final_allocation = round(actual_size / total_equity, 4)
            sig.position_size    = round(actual_size, 2)
            sig.quantity         = quantity
            approved.append(sig)

            remaining_heat  -= this_heat
            remaining_cash  -= actual_size
            sector_exposure[sig.sector] = current_sector_exp + sig.final_allocation

            logger.info(
                f"ALLOCATED {sig.symbol}: "
                f"Kelly={sig.kelly_fraction:.1%} → alloc={sig.final_allocation:.1%} "
                f"₹{actual_size:.0f} ({quantity} shares) "
                f"heat_used={this_heat:.2%} remaining_heat={remaining_heat:.2%}"
            )

        # 7. Estimate portfolio Sharpe
        if approved:
            expected_returns = [s.confidence * s.tp_pct - (1 - s.confidence) * s.sl_pct
                                for s in approved]
            weights = [s.final_allocation for s in approved]
            portfolio_return = sum(r * w for r, w in zip(expected_returns, weights))
            portfolio_risk   = math.sqrt(sum(w**2 * s.sl_pct**2
                                            for w, s in zip(weights, approved)))
            sharpe = portfolio_return / portfolio_risk if portfolio_risk > 0 else 0
        else:
            sharpe = 0

        total_deployed = sum(s.position_size for s in approved)
        total_heat     = existing_heat + sum(s.final_allocation * s.sl_pct for s in approved)

        explanation = (
            f"Portfolio engine: {len(signals)} signals → {len(approved)} positions. "
            f"Deploy ₹{total_deployed:.0f} ({total_deployed/total_equity:.0%} of equity). "
            f"Heat {existing_heat:.1%} → {total_heat:.1%}. "
            f"Est. Sharpe {sharpe:.2f}. "
            f"Rejected {len(rejected_sigs)} signals."
        )
        logger.info(explanation)

        return PortfolioAllocation(
            candidates_in   = len(signals),
            positions_out   = len(approved),
            allocations     = approved,
            rejected        = rejected_sigs,
            total_deployed  = total_deployed,
            total_heat      = total_heat,
            existing_heat   = existing_heat,
            sharpe_estimate = round(sharpe, 3),
            explanation     = explanation,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _kelly(self, confidence: float, sl_pct: float, tp_pct: float) -> float:
        """Raw Kelly fraction for a single trade."""
        if sl_pct <= 0 or tp_pct <= 0:
            return 0.0
        p = confidence
        q = 1.0 - confidence
        b = tp_pct / sl_pct
        return max(0.0, (p * b - q) / b)

    def _compute_heat(self, open_positions: list[dict], total_equity: float) -> float:
        """Total portfolio heat from existing open positions."""
        if not open_positions or total_equity <= 0:
            return 0.0
        heat = 0.0
        for pos in open_positions:
            size   = pos.get('position_size', 0) or 0
            sl_pct = pos.get('sl_pct', 0.03) or 0.03
            heat  += (size / total_equity) * sl_pct
        return round(heat, 4)

    def _group_by_correlation(
        self,
        signals: list[CandidateSignal],
        fetch_history_fn,
    ) -> dict[int, list[CandidateSignal]]:
        """
        Group signals by return correlation. Correlated stocks (r > 0.70)
        are grouped together and treated as one Kelly bet.
        """
        symbols = [s.symbol for s in signals]
        returns: dict[str, pd.Series] = {}

        for sym in symbols:
            try:
                df = fetch_history_fn(sym, period_days=CORRELATION_WINDOW, interval='1d')
                if df is not None and len(df) > 20:
                    ret = pd.Series(df['close'].values).pct_change().dropna()
                    returns[sym] = ret
            except Exception as e:
                logger.debug(f"Correlation fetch failed for {sym}: {e}")

        if len(returns) < 2:
            return {i: [sig] for i, sig in enumerate(signals)}

        # Align series lengths
        min_len = min(len(r) for r in returns.values())
        aligned = {sym: r.values[-min_len:] for sym, r in returns.items()}

        # Build correlation matrix
        symbols_with_data = list(aligned.keys())
        matrix = np.corrcoef([aligned[s] for s in symbols_with_data])

        # Union-find grouping
        n = len(symbols_with_data)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            parent[find(x)] = find(y)

        for i in range(n):
            for j in range(i + 1, n):
                if abs(matrix[i][j]) >= HIGH_CORRELATION_THRESH:
                    union(i, j)
                    logger.debug(
                        f"Correlated: {symbols_with_data[i]} ↔ {symbols_with_data[j]} "
                        f"r={matrix[i][j]:.2f}"
                    )

        # Map symbols to groups
        sym_to_group = {sym: find(i) for i, sym in enumerate(symbols_with_data)}

        # Signals without data get their own group
        groups: dict[int, list[CandidateSignal]] = {}
        group_counter = n  # start fresh group IDs after correlation groups
        for sig in signals:
            if sig.symbol in sym_to_group:
                gid = sym_to_group[sig.symbol]
            else:
                gid = group_counter
                group_counter += 1
            groups.setdefault(gid, []).append(sig)

        return groups


_engine: Optional[PortfolioEngine] = None

def get_portfolio_engine() -> PortfolioEngine:
    global _engine
    if _engine is None:
        _engine = PortfolioEngine()
    return _engine
