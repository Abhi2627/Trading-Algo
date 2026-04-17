# =============================================================================
# 02_feature_engineering.py
# Kaggle Notebook — Feature Engineering
# =============================================================================
# HOW TO USE:
# 1. Create a new Kaggle notebook
# 2. Add dataset: abhay1226/trading-platform-ohlcv-v2
# 3. Set accelerator: None (CPU is fine for this)
# 4. Paste this entire file as cells
# 5. Run All — takes ~5 minutes
# 6. Save Version -> Save & Run All
# 7. Go to Output tab -> Save as Dataset -> "trading-platform-features"
# =============================================================================

# ── Cell 1: Install dependencies ─────────────────────────────────────────────
import subprocess
subprocess.run(["pip", "install", "pandas-ta", "-q"], check=True)

# ── Cell 2: Imports ───────────────────────────────────────────────────────────
import os
import numpy as np
import pandas as pd
import pandas_ta as ta
import json
from pathlib import Path

INPUT_DIR  = Path("/kaggle/input/trading-platform-ohlcv-v2")
OUTPUT_DIR = Path("/kaggle/working/features")
OUTPUT_DIR.mkdir(exist_ok=True)

print(f"Input files: {list(INPUT_DIR.glob('*.csv'))}")

# ── Cell 3: Feature computation (mirrors services/market_data/features.py) ────
# CRITICAL: This must stay in sync with the backend feature engineering.
# If you change features here, update features.py in the backend too.

def compute_features(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or len(df) < 60:
        return None

    f = df.copy()

    # Returns
    f["return_1d"]     = f["close"].pct_change(1)
    f["return_3d"]     = f["close"].pct_change(3)
    f["return_5d"]     = f["close"].pct_change(5)
    f["return_10d"]    = f["close"].pct_change(10)
    f["return_20d"]    = f["close"].pct_change(20)
    f["log_return_1d"] = np.log(f["close"] / f["close"].shift(1))
    f["log_return_5d"] = np.log(f["close"] / f["close"].shift(5))

    # Volatility
    f["volatility_5d"]  = f["log_return_1d"].rolling(5).std()
    f["volatility_10d"] = f["log_return_1d"].rolling(10).std()
    f["volatility_20d"] = f["log_return_1d"].rolling(20).std()

    atr = ta.atr(f["high"], f["low"], f["close"], length=14)
    f["atr_14"] = atr
    f["atr_pct"] = f["atr_14"] / f["close"]

    # Price position
    rh52 = f["high"].rolling(252).max()
    rl52 = f["low"].rolling(252).min()
    f["price_position_52w"] = (f["close"] - rl52) / (rh52 - rl52 + 1e-9)
    rh20 = f["high"].rolling(20).max()
    rl20 = f["low"].rolling(20).min()
    f["price_position_20d"] = (f["close"] - rl20) / (rh20 - rl20 + 1e-9)
    f["gap_pct"] = (f["open"] - f["close"].shift(1)) / f["close"].shift(1)

    # Trend
    f["ema_9"]   = ta.ema(f["close"], length=9)
    f["ema_21"]  = ta.ema(f["close"], length=21)
    f["ema_50"]  = ta.ema(f["close"], length=50)
    f["ema_200"] = ta.ema(f["close"], length=200)
    f["close_vs_ema9"]    = (f["close"] - f["ema_9"])   / f["ema_9"]
    f["close_vs_ema21"]   = (f["close"] - f["ema_21"])  / f["ema_21"]
    f["close_vs_ema50"]   = (f["close"] - f["ema_50"])  / f["ema_50"]
    f["close_vs_ema200"]  = (f["close"] - f["ema_200"]) / f["ema_200"]
    f["ema9_above_ema21"]  = (f["ema_9"]  > f["ema_21"]).astype(int)
    f["ema21_above_ema50"] = (f["ema_21"] > f["ema_50"]).astype(int)
    f["ema50_above_ema200"]= (f["ema_50"] > f["ema_200"]).astype(int)

    macd_df = ta.macd(f["close"], fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        f["macd_line"]         = macd_df.iloc[:, 0]
        f["macd_signal"]       = macd_df.iloc[:, 2]
        f["macd_histogram"]    = macd_df.iloc[:, 1]
        f["macd_above_signal"] = (f["macd_line"] > f["macd_signal"]).astype(int)
    else:
        f["macd_line"] = f["macd_signal"] = f["macd_histogram"] = f["macd_above_signal"] = 0.0

    adx_df = ta.adx(f["high"], f["low"], f["close"], length=14)
    f["adx"] = adx_df.iloc[:, 0] if adx_df is not None and not adx_df.empty else 0.0

    # Momentum
    f["rsi_14"]       = ta.rsi(f["close"], length=14)
    f["rsi_7"]        = ta.rsi(f["close"], length=7)
    f["rsi_overbought"] = (f["rsi_14"] > 70).astype(int)
    f["rsi_oversold"]   = (f["rsi_14"] < 30).astype(int)

    stoch_df = ta.stoch(f["high"], f["low"], f["close"], k=14, d=3)
    if stoch_df is not None and not stoch_df.empty:
        f["stoch_k"] = stoch_df.iloc[:, 0]
        f["stoch_d"] = stoch_df.iloc[:, 1]
    else:
        f["stoch_k"] = f["stoch_d"] = 50.0

    f["williams_r"] = ta.willr(f["high"], f["low"], f["close"], length=14)

    # Bollinger Bands
    bb_df = ta.bbands(f["close"], length=20, std=2)
    if bb_df is not None and not bb_df.empty:
        f["bb_upper"]    = bb_df.iloc[:, 0]
        f["bb_mid"]      = bb_df.iloc[:, 1]
        f["bb_lower"]    = bb_df.iloc[:, 2]
        f["bb_width"]    = (f["bb_upper"] - f["bb_lower"]) / f["bb_mid"]
        f["bb_position"] = (f["close"] - f["bb_lower"]) / (f["bb_upper"] - f["bb_lower"] + 1e-9)
    else:
        f["bb_width"] = f["bb_position"] = 0.5

    # Volume
    f["volume_ma_20"]  = f["volume"].rolling(20).mean()
    f["volume_ratio"]  = f["volume"] / (f["volume_ma_20"] + 1e-9)
    f["volume_spike"]  = (f["volume_ratio"] > 2.0).astype(int)
    f["obv"]           = ta.obv(f["close"], f["volume"])
    f["obv_ma_20"]     = f["obv"].rolling(20).mean()
    f["obv_above_ma"]  = (f["obv"] > f["obv_ma_20"]).astype(int)
    vwap = (f["close"] * f["volume"]).rolling(20).sum() / f["volume"].rolling(20).sum()
    f["vwap_deviation"] = (f["close"] - vwap) / vwap

    # Regime
    f["is_trending"] = (
        (f["adx"] > 25) &
        (f["ema9_above_ema21"] == f["ema21_above_ema50"])
    ).astype(int)
    atr_q = f["atr_pct"].rolling(60).quantile(0.75)
    f["is_high_volatility"] = (f["atr_pct"] > atr_q).astype(int)

    # Keep only feature columns (drop raw OHLC, keep close for target)
    drop_cols = ["open", "high", "low", "volume"]
    f = f[[c for c in f.columns if c not in drop_cols]]
    f = f.dropna()
    return f if not f.empty else None


# ── Cell 4: Process all symbols ───────────────────────────────────────────────
feature_list = []
meta = {}

for csv_path in sorted(INPUT_DIR.glob("*.csv")):
    symbol = csv_path.stem  # e.g. RELIANCE_NS
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        df.columns = [c.lower() for c in df.columns]

        # Ensure required columns exist
        required = ["open", "high", "low", "close", "volume"]
        if not all(c in df.columns for c in required):
            print(f"SKIP {symbol} — missing columns: {df.columns.tolist()}")
            continue

        features = compute_features(df)
        if features is None:
            print(f"SKIP {symbol} — not enough data after feature computation")
            continue

        # Save as CSV (preserves column names for inspection)
        out_path = OUTPUT_DIR / f"{symbol}_features.csv"
        features.to_csv(out_path)

        # Also save as numpy array for fast loading during training
        arr = features.values.astype(np.float32)
        np.save(OUTPUT_DIR / f"{symbol}_features.npy", arr)

        meta[symbol] = {
            "rows":     len(features),
            "cols":     len(features.columns),
            "columns":  features.columns.tolist(),
            "date_start": str(features.index[0]),
            "date_end":   str(features.index[-1]),
        }
        print(f"OK  {symbol:25s}  {len(features)} rows x {len(features.columns)} features")

    except Exception as e:
        print(f"ERR {symbol}: {e}")
        import traceback; traceback.print_exc()

# Save metadata (column names must be identical across all symbols for training)
with open(OUTPUT_DIR / "meta.json", "w") as f:
    json.dump(meta, f, indent=2)

print(f"\nDone. Processed {len(meta)} symbols.")

# ── Cell 5: Validation ────────────────────────────────────────────────────────
# Verify all symbols have identical feature columns (required for training)
all_cols = [v["columns"] for v in meta.values()]
first = all_cols[0]
mismatch = [sym for sym, cols in zip(meta.keys(), all_cols) if cols != first]

if mismatch:
    print(f"WARNING: Column mismatch in: {mismatch}")
else:
    print(f"All {len(meta)} symbols have identical {len(first)} feature columns.")
    print(f"Feature columns:\n{json.dumps(first, indent=2)}")
