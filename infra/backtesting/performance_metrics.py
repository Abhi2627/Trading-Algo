# infra/backtesting/performance_metrics.py
# Everything needed to evaluate whether a strategy has real edge.
# Primary metrics: Sharpe, Max Drawdown, Calmar, Profit Factor.
# Secondary metrics: Win rate, avg win/loss, expectancy.
#
# Rule of thumb for going live:
#   Sharpe > 1.5  (on OUT-OF-SAMPLE data only)
#   Max DD < 15%
#   Min 200 trades (statistical significance)
#   Profit factor > 1.5

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Trade:
    """A single completed trade record from the backtest."""
    symbol:       str
    entry_date:   pd.Timestamp
    exit_date:    pd.Timestamp
    entry_price:  float
    exit_price:   float
    quantity:     int
    side:         str           # 'long' (only long for now)
    pnl:          float         # after all costs
    pnl_pct:      float         # pnl / (entry_price * quantity)
    cost:         float         # total transaction cost
    signal_confidence: float    # confidence at entry
    market_regime:     str      # trending / ranging / volatile


@dataclass
class PerformanceReport:
    """Full performance summary for a backtest run."""
    # Core metrics
    total_return_pct:   float
    cagr_pct:           float
    sharpe_ratio:       float
    monthly_sharpe:     float   # correct metric for positional strategies
    sortino_ratio:      float
    calmar_ratio:       float
    max_drawdown_pct:   float
    max_drawdown_duration_days: int

    # Trade statistics
    total_trades:       int
    winning_trades:     int
    losing_trades:      int
    win_rate_pct:       float
    avg_win_pct:        float
    avg_loss_pct:       float
    profit_factor:      float   # gross profit / gross loss
    expectancy_pct:     float   # expected return per trade
    avg_holding_days:   float

    # Cost analysis
    total_costs:        float
    cost_as_pct_of_pnl: float

    # Benchmark comparison
    nifty_return_pct:   Optional[float] = None
    alpha_pct:          Optional[float] = None

    # Per-regime breakdown
    regime_breakdown:   dict = field(default_factory=dict)

    # Confidence breakdown (does higher confidence = better returns?)
    confidence_breakdown: dict = field(default_factory=dict)

    def is_live_ready(self) -> bool:
        """
        Hard rules for a positional delivery strategy (avg hold 30-120 days).
        Note: Sharpe based on MONTHLY returns, not daily — daily Sharpe is
        misleading for low-frequency strategies where most days have 0 activity.
        """
        return (
            self.calmar_ratio    >= 0.5    and  # return/drawdown ratio
            self.max_drawdown_pct <= 15.0  and
            self.total_trades    >= 50     and  # reduced from 200 for positional
            self.profit_factor   >= 1.5   and
            self.win_rate_pct    >= 40.0  and
            self.expectancy_pct  > 0.0
        )

    def summary(self) -> str:
        lines = [
            "=" * 50,
            "  BACKTEST PERFORMANCE REPORT",
            "=" * 50,
            f"  Total Return:      {self.total_return_pct:+.2f}%",
            f"  CAGR:              {self.cagr_pct:+.2f}%",
            f"  Sharpe (daily):    {self.sharpe_ratio:.3f}",
            f"  Sharpe (monthly):  {self.monthly_sharpe:.3f}  <- use this for positional",
            f"  Sortino Ratio:     {self.sortino_ratio:.3f}",
            f"  Calmar Ratio:      {self.calmar_ratio:.3f}",
            f"  Max Drawdown:      {self.max_drawdown_pct:.2f}%",
            f"  DD Duration:       {self.max_drawdown_duration_days} days",
            "-" * 50,
            f"  Total Trades:      {self.total_trades}",
            f"  Win Rate:          {self.win_rate_pct:.1f}%",
            f"  Avg Win:           {self.avg_win_pct:+.2f}%",
            f"  Avg Loss:          {self.avg_loss_pct:+.2f}%",
            f"  Profit Factor:     {self.profit_factor:.3f}",
            f"  Expectancy/trade:  {self.expectancy_pct:+.4f}%",
            f"  Avg Holding:       {self.avg_holding_days:.1f} days",
            "-" * 50,
            f"  Total Costs:       \u20b9{self.total_costs:.2f}",
            f"  Costs/PnL:         {self.cost_as_pct_of_pnl:.1f}%",
            "=" * 50,
            f"  LIVE READY:        {chr(9989) + ' YES' if self.is_live_ready() else chr(10060) + ' NO'}",
            "=" * 50,
        ]
        if self.nifty_return_pct is not None:
            lines.insert(-2, f"  Alpha vs Nifty:    {self.alpha_pct:+.2f}%")
        return "\n".join(lines)


class PerformanceCalculator:
    """Computes all performance metrics from a list of completed trades."""

    RISK_FREE_RATE = 0.065   # 6.5% — RBI repo rate approximation
    TRADING_DAYS   = 252     # NSE trading days per year

    def compute(
        self,
        trades:          List[Trade],
        equity_curve:    pd.Series,   # daily portfolio value
        start_capital:   float,
        nifty_returns:   Optional[pd.Series] = None,
    ) -> PerformanceReport:
        """Main entry point. Pass all completed trades + daily equity curve."""

        if not trades:
            raise ValueError("No trades to analyse")
        if len(trades) < 10:
            print("WARNING: fewer than 10 trades — metrics will not be statistically meaningful")

        pnl_series  = pd.Series([t.pnl     for t in trades])
        pct_series  = pd.Series([t.pnl_pct for t in trades])
        cost_series = pd.Series([t.cost    for t in trades])

        winners = pct_series[pct_series > 0]
        losers  = pct_series[pct_series < 0]

        # ----------------------------------------------------------------
        # Return metrics
        # ----------------------------------------------------------------
        final_equity    = equity_curve.iloc[-1]
        total_return    = (final_equity - start_capital) / start_capital * 100

        n_years = (
            equity_curve.index[-1] - equity_curve.index[0]
        ).days / 365.25
        cagr = ((final_equity / start_capital) ** (1 / max(n_years, 0.01)) - 1) * 100

        # ----------------------------------------------------------------
        # Risk-adjusted returns
        # ----------------------------------------------------------------
        daily_returns = equity_curve.pct_change().dropna()
        excess_daily  = daily_returns - (self.RISK_FREE_RATE / self.TRADING_DAYS)

        sharpe  = self._sharpe(excess_daily)
        sortino = self._sortino(excess_daily, daily_returns)

        # Monthly Sharpe — correct metric for positional strategies
        monthly_equity  = equity_curve.resample('ME').last()
        monthly_returns = monthly_equity.pct_change().dropna()
        monthly_excess  = monthly_returns - (self.RISK_FREE_RATE / 12)
        monthly_sharpe  = (
            float(monthly_excess.mean() / monthly_excess.std() * np.sqrt(12))
            if monthly_excess.std() > 0 else 0.0
        )

        # ----------------------------------------------------------------
        # Drawdown
        # ----------------------------------------------------------------
        max_dd_pct, max_dd_days = self._max_drawdown(equity_curve)
        calmar = abs(cagr / max_dd_pct) if max_dd_pct != 0 else 0.0

        # ----------------------------------------------------------------
        # Trade stats
        # ----------------------------------------------------------------
        win_rate    = len(winners) / len(trades) * 100 if trades else 0
        avg_win     = winners.mean() * 100 if len(winners) > 0 else 0.0
        avg_loss    = losers.mean()  * 100 if len(losers)  > 0 else 0.0
        gross_profit = winners.sum()
        gross_loss   = abs(losers.sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        expectancy  = pct_series.mean() * 100

        holding_days = [
            (t.exit_date - t.entry_date).days for t in trades
        ]
        avg_holding = np.mean(holding_days)

        # ----------------------------------------------------------------
        # Costs
        # ----------------------------------------------------------------
        total_costs = cost_series.sum()
        gross_pnl   = pnl_series.sum() + total_costs  # before costs
        cost_ratio  = (total_costs / gross_pnl * 100) if gross_pnl > 0 else 0.0

        # ----------------------------------------------------------------
        # Benchmark
        # ----------------------------------------------------------------
        alpha = None
        nifty_ret = None
        if nifty_returns is not None:
            nifty_ret = nifty_returns.sum() * 100
            alpha     = total_return - nifty_ret

        # ----------------------------------------------------------------
        # Regime breakdown
        # ----------------------------------------------------------------
        regime_breakdown = {}
        for regime in ['trending', 'ranging', 'volatile']:
            subset = [t for t in trades if t.market_regime == regime]
            if subset:
                regime_pnl = pd.Series([t.pnl_pct for t in subset])
                regime_breakdown[regime] = {
                    'count':    len(subset),
                    'win_rate': (regime_pnl > 0).mean() * 100,
                    'avg_pct':  regime_pnl.mean() * 100,
                }

        # ----------------------------------------------------------------
        # Confidence breakdown (validates if confidence score is meaningful)
        # ----------------------------------------------------------------
        conf_bins = [(0.4, 0.55), (0.55, 0.70), (0.70, 0.85), (0.85, 1.0)]
        confidence_breakdown = {}
        for lo, hi in conf_bins:
            subset = [t for t in trades if lo <= t.signal_confidence < hi]
            if subset:
                subset_pnl = pd.Series([t.pnl_pct for t in subset])
                confidence_breakdown[f"{lo:.0%}-{hi:.0%}"] = {
                    'count':    len(subset),
                    'win_rate': (subset_pnl > 0).mean() * 100,
                    'avg_pct':  subset_pnl.mean() * 100,
                }

        return PerformanceReport(
            total_return_pct=round(total_return, 4),
            cagr_pct=round(cagr, 4),
            sharpe_ratio=round(sharpe, 4),
            monthly_sharpe=round(monthly_sharpe, 4),
            sortino_ratio=round(sortino, 4),
            calmar_ratio=round(calmar, 4),
            max_drawdown_pct=round(max_dd_pct, 4),
            max_drawdown_duration_days=max_dd_days,
            total_trades=len(trades),
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate_pct=round(win_rate, 2),
            avg_win_pct=round(avg_win, 4),
            avg_loss_pct=round(avg_loss, 4),
            profit_factor=round(profit_factor, 4),
            expectancy_pct=round(expectancy, 6),
            avg_holding_days=round(avg_holding, 1),
            total_costs=round(total_costs, 2),
            cost_as_pct_of_pnl=round(cost_ratio, 2),
            nifty_return_pct=round(nifty_ret, 4) if nifty_ret else None,
            alpha_pct=round(alpha, 4) if alpha else None,
            regime_breakdown=regime_breakdown,
            confidence_breakdown=confidence_breakdown,
        )

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------

    def _sharpe(self, excess_daily: pd.Series) -> float:
        std = excess_daily.std()
        if std == 0:
            return 0.0
        return float(excess_daily.mean() / std * np.sqrt(self.TRADING_DAYS))

    def _sortino(self, excess_daily: pd.Series, daily_returns: pd.Series) -> float:
        """Sortino only penalises downside deviation, not upside volatility."""
        downside = daily_returns[daily_returns < 0]
        downside_std = downside.std()
        if downside_std == 0:
            return 0.0
        return float(excess_daily.mean() / downside_std * np.sqrt(self.TRADING_DAYS))

    def _max_drawdown(self, equity: pd.Series) -> tuple[float, int]:
        """Returns (max_drawdown_pct, duration_in_days)."""
        peak      = equity.cummax()
        drawdown  = (equity - peak) / peak * 100
        max_dd    = abs(drawdown.min())

        # Duration: longest consecutive period below peak
        in_dd = drawdown < 0
        max_dur = 0
        cur_dur = 0
        for val in in_dd:
            if val:
                cur_dur += 1
                max_dur = max(max_dur, cur_dur)
            else:
                cur_dur = 0

        return float(max_dd), max_dur
