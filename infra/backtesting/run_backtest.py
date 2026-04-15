#!/usr/bin/env python
# infra/backtesting/run_backtest.py
# Usage: cd infra/backtesting && python run_backtest.py

import sys, os

# Load .env BEFORE importing any backend modules
# backend's config.py reads env vars at import time
env_path = os.path.join(os.path.dirname(__file__), '..', '..', 'apps', 'backend', '.env')
from dotenv import load_dotenv
load_dotenv(env_path, override=True)
print(f"Loaded .env from {os.path.abspath(env_path)}")

from backtest_engine import BacktestEngine, BacktestConfig
from walk_forward import WalkForwardValidator, WalkForwardConfig
from performance_metrics import PerformanceCalculator

# -----------------------------------------------------------------------
# Config — adjust these
# -----------------------------------------------------------------------
SYMBOLS = [
    'NSE:RELIANCE', 'NSE:TCS', 'NSE:HDFCBANK',
    'NSE:INFY', 'NSE:ICICIBANK', 'NSE:SBIN',
    'NSE:BHARTIARTL', 'NSE:KOTAKBANK', 'NSE:LT',
    'NSE:AXISBANK', 'NSE:MARUTI', 'NSE:WIPRO',
]
START_DATE      = '2022-01-01'
END_DATE        = '2024-12-31'
INITIAL_CAPITAL = 100000.0
MIN_CONFIDENCE  = 0.60  # raised from 0.55

# -----------------------------------------------------------------------
# 0. Diagnostic — check what feature values actually look like
# -----------------------------------------------------------------------
print("=" * 55)
print("STEP 0: Feature Diagnostic (first 3 BUY-able days)")
print("=" * 55)

import sys, os as _os
import pandas as pd
sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', '..', 'apps', 'backend'))
from services.market_data.fetcher import fetch_historical
from services.market_data.features import compute_features, detect_market_regime

df = fetch_historical('NSE:RELIANCE', period_days=1825)
if df is not None:
    features_df = compute_features(df)
    if features_df is not None:
        last = features_df.iloc[-1]
        print(f"NSE:RELIANCE latest features:")
        for k in ['rsi_14','ema50_above_ema200','close_vs_ema50','adx','volume_ratio','macd_line']:
            print(f"  {k:25s} = {last.get(k, 'MISSING')}")
        print(f"  Valid rows after dropna: {len(features_df)}")
        print(f"  Feature range: {features_df.index[0].date()} to {features_df.index[-1].date()}")
        print(f"  Regime: {detect_market_regime(df)}")
        buy_days = features_df[
            (features_df['rsi_14'] >= 40) & (features_df['rsi_14'] <= 65) &
            (features_df['ema50_above_ema200'] == 1) &
            (features_df['close_vs_ema50'] > 0) &
            (features_df['macd_line'] > 0)
        ]
        print(f"  Days meeting all BUY conditions: {len(buy_days)} / {len(features_df)}")
        test_date = pd.Timestamp('2023-06-01')
        sliced = features_df[features_df.index <= test_date]
        print(f"  Slice to 2023-06-01: {len(sliced)} rows")
        if len(buy_days) > 0:
            print(f"  First BUY day: {buy_days.index[0].date()}")
            print(f"  Last BUY day:  {buy_days.index[-1].date()}")
print()

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
