# api/routes/backtest.py
# Backtesting API — run strategy backtests from the Tauri UI.
import logging
import sys
import os
from fastapi import APIRouter, Security, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backtest", tags=["backtest"])

# Add infra/backtesting to path
_infra_path = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'infra', 'backtesting'
)
if os.path.exists(_infra_path) and _infra_path not in sys.path:
    sys.path.insert(0, os.path.abspath(_infra_path))


class BacktestRequest(BaseModel):
    symbols:         list[str]
    start_date:      str          = "2022-01-01"
    end_date:        str          = "2024-12-31"
    initial_capital: float        = 100_000.0
    min_confidence:  float        = 0.70
    stop_loss_pct:   float        = 0.03
    take_profit_pct: float        = 0.08
    time_exit_days:  int          = 7
    walk_forward:    bool         = False
    train_months:    int          = 18
    test_months:     int          = 6


@router.post("/run")
async def run_backtest(
    req: BacktestRequest,
    _: str = Security(lambda: None),  # auth handled at app level
):
    """
    Run a backtest with the given parameters.
    Returns trades, equity curve, and performance metrics.
    Takes 30-120 seconds depending on symbol count and date range.
    """
    import asyncio

    def _run_sync():
        try:
            from backtest_engine import BacktestEngine, BacktestConfig
            from performance_metrics import PerformanceCalculator
        except ImportError as e:
            raise HTTPException(status_code=500, detail=f"Backtest engine not found: {e}")

        cfg = BacktestConfig(
            symbols         = req.symbols,
            start_date      = req.start_date,
            end_date        = req.end_date,
            initial_capital = req.initial_capital,
            min_confidence  = req.min_confidence,
        )
        engine = BacktestEngine(cfg)
        result = engine.run()

        trades       = result.get("trades", [])
        equity_curve = result.get("equity_curve", [])

        if not trades:
            return {
                "success":      True,
                "trades":       [],
                "equity_curve": equity_curve,
                "metrics":      None,
                "message":      "No trades generated. Try lowering min_confidence or extending date range.",
            }

        calc   = PerformanceCalculator()
        report = calc.compute(
            trades        = trades,
            equity_curve  = equity_curve,
            start_capital = req.initial_capital,
        )

        return {
            "success":      True,
            "trades":       trades[:200],  # cap at 200 for response size
            "trade_count":  len(trades),
            "equity_curve": equity_curve,
            "metrics": {
                "total_return_pct":  round(report.total_return_pct, 2),
                "cagr_pct":          round(report.cagr_pct, 2),
                "sharpe":            round(report.sharpe, 3),
                "sortino":           round(report.sortino, 3),
                "calmar":            round(report.calmar, 3),
                "max_drawdown_pct":  round(report.max_drawdown_pct, 2),
                "win_rate_pct":      round(report.win_rate_pct, 2),
                "profit_factor":     round(report.profit_factor, 3),
                "avg_win_pct":       round(report.avg_win_pct, 2),
                "avg_loss_pct":      round(report.avg_loss_pct, 2),
                "total_trades":      report.total_trades,
                "winning_trades":    report.winning_trades,
                "losing_trades":     report.losing_trades,
                "is_live_ready":     report.is_live_ready(),
            },
            "message": "Backtest complete",
        }

    # Run blocking backtest in thread pool
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_sync)
    return result


@router.get("/presets")
async def get_presets():
    """Return preset backtest configurations for the UI."""
    return {
        "presets": [
            {
                "name":            "Current Strategy (v3)",
                "description":     "Live strategy parameters — validates what's running now",
                "min_confidence":  0.70,
                "stop_loss_pct":   0.03,
                "take_profit_pct": 0.08,
                "time_exit_days":  7,
                "symbols":         [
                    "NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK",
                    "NSE:INFY", "NSE:ICICIBANK", "NSE:SBIN",
                    "NSE:BHARTIARTL", "NSE:KOTAKBANK", "NSE:LT",
                    "NSE:AXISBANK", "NSE:MARUTI", "NSE:WIPRO",
                ],
            },
            {
                "name":            "Aggressive (High Confidence)",
                "description":     "Only very high confidence signals — fewer trades, higher quality",
                "min_confidence":  0.80,
                "stop_loss_pct":   0.04,
                "take_profit_pct": 0.12,
                "time_exit_days":  10,
                "symbols":         [
                    "NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK",
                    "NSE:INFY", "NSE:ICICIBANK",
                ],
            },
            {
                "name":            "Conservative (Tight Stops)",
                "description":     "Wider net, tight stops — tests SL sensitivity",
                "min_confidence":  0.65,
                "stop_loss_pct":   0.02,
                "take_profit_pct": 0.06,
                "time_exit_days":  5,
                "symbols":         [
                    "NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK",
                    "NSE:INFY", "NSE:ICICIBANK", "NSE:SBIN",
                    "NSE:BHARTIARTL", "NSE:KOTAKBANK", "NSE:LT",
                    "NSE:AXISBANK", "NSE:MARUTI", "NSE:WIPRO",
                ],
            },
        ]
    }
