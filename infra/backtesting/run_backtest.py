#!/usr/bin/env python
# infra/backtesting/run_backtest.py
# Usage: cd infra/backtesting && python run_backtest.py
# Runs both a single backtest AND a walk-forward validation.

from backtest_engine import BacktestEngine, BacktestConfig
from walk_forward import WalkForwardValidator, WalkForwardConfig
from performance_metrics import PerformanceCalculator
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend', '.env'))

# -----------------------------------------------------------------------
# Config — adjust these
# -----------------------------------------------------------------------
SYMBOLS = [
    'NSE:RELIANCE', 'NSE:TCS', 'NSE:HDFCBANK',
    'NSE:INFY', 'NSE:ICICIBANK', 'NSE:SBIN',
]
START_DATE      = '2022-01-01'
END_DATE        = '2024-12-31'
INITIAL_CAPITAL = 100000.0
MIN_CONFIDENCE  = 0.55

# -----------------------------------------------------------------------
# 1. Single backtest (quick sanity check)
# -----------------------------------------------------------------------
print("=" * 55)
print("STEP 1: Single Backtest")
print("=" * 55)

cfg    = BacktestConfig(
    symbols=SYMBOLS,
    start_date=START_DATE,
    end_date=END_DATE,
    initial_capital=INITIAL_CAPITAL,
    min_confidence=MIN_CONFIDENCE,
)
engine = BacktestEngine(cfg)
result = engine.run()

trades       = result["trades"]
equity_curve = result["equity_curve"]

if trades:
    calc   = PerformanceCalculator()
    report = calc.compute(
        trades=trades,
        equity_curve=equity_curve,
        start_capital=INITIAL_CAPITAL,
    )
    print(report.summary())
else:
    print("No trades generated. Lower min_confidence or extend date range.")

# -----------------------------------------------------------------------
# 2. Walk-forward validation (the real test)
# -----------------------------------------------------------------------
print("\n" + "=" * 55)
print("STEP 2: Walk-Forward Validation")
print("=" * 55)

wf_cfg = WalkForwardConfig(
    symbols=SYMBOLS,
    full_start='2021-01-01',
    full_end='2024-12-31',
    train_months=18,
    test_months=6,
    initial_capital=INITIAL_CAPITAL,
    min_confidence=MIN_CONFIDENCE,
)
validator = WalkForwardValidator(wf_cfg)
wf_result = validator.run()
