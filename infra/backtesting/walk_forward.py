# infra/backtesting/walk_forward.py
# Walk-forward validation — the only honest way to test a strategy.
#
# Simple backtest = in-sample test. You can always overfit to past data.
# Walk-forward = rolling windows of train + out-of-sample test periods.
# If the strategy holds up across MULTIPLE out-of-sample windows, it has edge.
#
# Window structure used here:
#   [------- train 18 months -------][-- test 6 months --]
#                     [------- train 18 months -------][-- test 6 months --]
#                                       (slides forward 6 months each time)

import sys, os

_env = os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend', '.env')
if os.path.exists(_env):
    from dotenv import load_dotenv
    load_dotenv(_env, override=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend'))

import pandas as pd
from dataclasses import dataclass
from backtest_engine import BacktestConfig, BacktestEngine
from performance_metrics import PerformanceCalculator, PerformanceReport


@dataclass
class WalkForwardConfig:
    symbols:         list
    full_start:      str    # earliest date in full dataset e.g. '2021-01-01'
    full_end:        str    # latest date e.g. '2024-12-31'
    train_months:    int  = 18
    test_months:     int  = 6
    initial_capital: float = 100000.0
    min_confidence:  float = 0.50


class WalkForwardValidator:
    """
    Runs multiple train/test windows and aggregates out-of-sample results.
    The out-of-sample Sharpe is the number that matters — not the in-sample.
    """

    def __init__(self, config: WalkForwardConfig):
        self.cfg  = config
        self.calc = PerformanceCalculator()

    def run(self) -> dict:
        windows = self._build_windows()
        print(f"Walk-forward: {len(windows)} windows")
        print(f"Train: {self.cfg.train_months}m | Test: {self.cfg.test_months}m\n")

        oos_trades     = []   # all out-of-sample trades combined
        oos_equity_all = []   # list of equity series (one per window)
        window_results = []

        for idx, (train_start, train_end, test_start, test_end) in enumerate(windows):
            print(f"Window {idx+1}/{len(windows)}: "
                  f"train={train_start} to {train_end} | "
                  f"test={test_start} to {test_end}")

            cfg = BacktestConfig(
                symbols=self.cfg.symbols,
                start_date=test_start,
                end_date=test_end,
                initial_capital=self.cfg.initial_capital,
                min_confidence=self.cfg.min_confidence,
            )
            engine = BacktestEngine(cfg)
            result = engine.run()

            trades       = result["trades"]
            equity_curve = result["equity_curve"]

            if len(trades) >= 5:
                report = self.calc.compute(
                    trades=trades,
                    equity_curve=equity_curve,
                    start_capital=self.cfg.initial_capital,
                )
                window_results.append({
                    "window":     idx + 1,
                    "test_start": test_start,
                    "test_end":   test_end,
                    "trades":     len(trades),
                    "sharpe":     report.monthly_sharpe,
                    "return_pct": report.total_return_pct,
                    "max_dd":     report.max_drawdown_pct,
                    "win_rate":   report.win_rate_pct,
                    "profit_factor": report.profit_factor,
                })
                oos_trades.extend(trades)
                oos_equity_all.append(equity_curve)
                print(f"  -> {len(trades)} trades | Monthly Sharpe={report.monthly_sharpe:.3f} "
                      f"| Return={report.total_return_pct:+.2f}%\n")
            else:
                print(f"  -> Not enough trades ({len(trades)}), skipping metrics\n")

        return self._aggregate(window_results, oos_trades, oos_equity_all)

    def _aggregate(self, window_results, oos_trades, oos_equity_all) -> dict:
        if not window_results:
            return {"error": "No windows had sufficient trades"}

        import numpy as np
        sharpes    = [w["sharpe"]     for w in window_results]
        returns    = [w["return_pct"] for w in window_results]
        drawdowns  = [w["max_dd"]     for w in window_results]
        win_rates  = [w["win_rate"]   for w in window_results]
        pf         = [w["profit_factor"] for w in window_results]

        # Consistency score: what fraction of windows were profitable?
        profitable_windows = sum(1 for r in returns if r > 0)
        consistency = profitable_windows / len(window_results) * 100

        summary = {
            "windows_tested":      len(window_results),
            "windows_profitable":  profitable_windows,
            "consistency_pct":     round(consistency, 1),
            "avg_sharpe":          round(np.mean(sharpes), 3),
            "min_sharpe":          round(np.min(sharpes), 3),
            "avg_return_pct":      round(np.mean(returns), 2),
            "avg_max_dd_pct":      round(np.mean(drawdowns), 2),
            "avg_win_rate_pct":    round(np.mean(win_rates), 2),
            "avg_profit_factor":   round(np.mean(pf), 3),
            "total_oos_trades":    len(oos_trades),
            "window_detail":       window_results,
        }

        # Overall verdict
        is_robust = (
            summary["avg_sharpe"]       >= 1.0   and
            summary["consistency_pct"]  >= 60.0  and
            summary["avg_win_rate_pct"] >= 40.0  and
            summary["total_oos_trades"] >= 50
        )
        summary["is_robust"] = is_robust

        print("\n" + "=" * 55)
        print("  WALK-FORWARD SUMMARY")
        print("=" * 55)
        print(f"  Windows tested:     {summary['windows_tested']}")
        print(f"  Profitable windows: {summary['windows_profitable']} "
              f"({summary['consistency_pct']:.0f}%)")
        print(f"  Avg Sharpe (monthly): {summary['avg_sharpe']:.3f}")
        print(f"  Min Sharpe (monthly): {summary['min_sharpe']:.3f}")
        print(f"  Avg Return:         {summary['avg_return_pct']:+.2f}%")
        print(f"  Avg Max Drawdown:   {summary['avg_max_dd_pct']:.2f}%")
        print(f"  Avg Win Rate:       {summary['avg_win_rate_pct']:.1f}%")
        print(f"  Total OOS trades:   {summary['total_oos_trades']}")
        print("=" * 55)
        verdict = "ROBUST — consider paper trading" if is_robust else "NOT ROBUST — improve models first"
        print(f"  VERDICT: {verdict}")
        print("=" * 55)

        return summary

    def _build_windows(self) -> list:
        """Generate (train_start, train_end, test_start, test_end) tuples."""
        windows = []
        test_start = pd.Timestamp(self.cfg.full_start)
        full_end   = pd.Timestamp(self.cfg.full_end)

        while True:
            train_start = test_start
            train_end   = train_start + pd.DateOffset(months=self.cfg.train_months)
            test_end    = train_end   + pd.DateOffset(months=self.cfg.test_months)

            if test_end > full_end:
                break

            windows.append((
                train_start.strftime('%Y-%m-%d'),
                train_end.strftime('%Y-%m-%d'),
                train_end.strftime('%Y-%m-%d'),
                test_end.strftime('%Y-%m-%d'),
            ))
            test_start = test_start + pd.DateOffset(months=self.cfg.test_months)

        return windows
