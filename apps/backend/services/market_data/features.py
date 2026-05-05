# services/market_data/features.py
# Computes all technical indicators and derived features from raw OHLCV.
# Output of compute_features() is what every AI model receives as input.
# Never add model logic here — only feature computation.
import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def compute_features(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Takes a raw OHLCV DataFrame and returns a DataFrame enriched with
    80+ technical features. The last row is always the most recent candle.

    Input columns required: open, high, low, close, volume
    Returns None if input is too short to compute indicators.
    Minimum required rows: 200 (for EMA200 to be meaningful)
    """
    if df is None or len(df) < 60:
        logger.warning("Not enough rows to compute features (need >= 60)")
        return None

    f = df.copy()

    # -----------------------------------------------------------------------
    # 1. Returns (momentum features)
    # -----------------------------------------------------------------------
    f["return_1d"]  = f["close"].pct_change(1)
    f["return_3d"]  = f["close"].pct_change(3)
    f["return_5d"]  = f["close"].pct_change(5)
    f["return_10d"] = f["close"].pct_change(10)
    f["return_20d"] = f["close"].pct_change(20)

    # Log returns (better statistical properties for ML)
    f["log_return_1d"] = np.log(f["close"] / f["close"].shift(1))
    f["log_return_5d"] = np.log(f["close"] / f["close"].shift(5))

    # -----------------------------------------------------------------------
    # 2. Volatility
    # -----------------------------------------------------------------------
    f["volatility_5d"]  = f["log_return_1d"].rolling(5).std()
    f["volatility_10d"] = f["log_return_1d"].rolling(10).std()
    f["volatility_20d"] = f["log_return_1d"].rolling(20).std()

    # ATR — average true range (measures daily price range)
    atr = ta.atr(f["high"], f["low"], f["close"], length=14)
    f["atr_14"] = atr
    f["atr_pct"] = f["atr_14"] / f["close"]  # normalised ATR

    # -----------------------------------------------------------------------
    # 3. Price position features
    # -----------------------------------------------------------------------
    # Where is current price within 52-week range? (0 = at low, 1 = at high)
    rolling_high_52w = f["high"].rolling(252).max()
    rolling_low_52w  = f["low"].rolling(252).min()
    f["price_position_52w"] = (
        (f["close"] - rolling_low_52w) /
        (rolling_high_52w - rolling_low_52w + 1e-9)
    )

    # Where is price within last 20 candles range?
    rolling_high_20 = f["high"].rolling(20).max()
    rolling_low_20  = f["low"].rolling(20).min()
    f["price_position_20d"] = (
        (f["close"] - rolling_low_20) /
        (rolling_high_20 - rolling_low_20 + 1e-9)
    )

    # Overnight gap (open vs previous close)
    f["gap_pct"] = (f["open"] - f["close"].shift(1)) / f["close"].shift(1)

    # -----------------------------------------------------------------------
    # 4. Trend indicators
    # -----------------------------------------------------------------------
    # EMAs
    f["ema_9"]   = ta.ema(f["close"], length=9)
    f["ema_21"]  = ta.ema(f["close"], length=21)
    f["ema_50"]  = ta.ema(f["close"], length=50)
    f["ema_200"] = ta.ema(f["close"], length=200)

    # Price relative to EMAs (normalised distance)
    f["close_vs_ema9"]   = (f["close"] - f["ema_9"])   / f["ema_9"]
    f["close_vs_ema21"]  = (f["close"] - f["ema_21"])  / f["ema_21"]
    f["close_vs_ema50"]  = (f["close"] - f["ema_50"])  / f["ema_50"]
    f["close_vs_ema200"] = (f["close"] - f["ema_200"]) / f["ema_200"]

    # EMA crossover signals (binary)
    f["ema9_above_ema21"]  = (f["ema_9"]  > f["ema_21"]).astype(int)
    f["ema21_above_ema50"] = (f["ema_21"] > f["ema_50"]).astype(int)
    f["ema50_above_ema200"]= (f["ema_50"] > f["ema_200"]).astype(int)

    # MACD — use column name matching, not fragile positional iloc
    macd_df = ta.macd(f["close"], fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        cols = list(macd_df.columns)
        # Column naming varies by pandas_ta version:
        #   pandas_ta:         MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
        #   pandas_ta_classic: MACD_12_26_9, MACDs_12_26_9, MACDh_12_26_9  (or similar)
        # Detect by name prefix to be version-agnostic
        macd_col  = next((c for c in cols if c.startswith("MACD_")), None)
        macds_col = next((c for c in cols if c.startswith("MACDs_")), None)
        macdh_col = next((c for c in cols if c.startswith("MACDh_")), None)
        if macd_col and macds_col and macdh_col:
            f["macd_line"]      = macd_df[macd_col]
            f["macd_signal"]    = macd_df[macds_col]
            f["macd_histogram"] = macd_df[macdh_col]
        else:
            # Fallback: positional but log a warning
            logger.warning(f"MACD columns unexpected: {cols} — falling back to iloc")
            f["macd_line"]      = macd_df.iloc[:, 0]
            f["macd_signal"]    = macd_df.iloc[:, min(2, len(cols)-1)]
            f["macd_histogram"] = macd_df.iloc[:, min(1, len(cols)-1)]
        f["macd_above_signal"] = (f["macd_line"] > f["macd_signal"]).astype(int)
    else:
        f["macd_line"] = f["macd_signal"] = f["macd_histogram"] = 0.0
        f["macd_above_signal"] = 0

    # ADX — detect column by name prefix, not fragile positional iloc
    adx_df = ta.adx(f["high"], f["low"], f["close"], length=14)
    if adx_df is not None and not adx_df.empty:
        cols = list(adx_df.columns)
        adx_col = next((c for c in cols if c.startswith("ADX")), None)
        if adx_col:
            f["adx"] = adx_df[adx_col]
        else:
            logger.warning(f"ADX columns unexpected: {cols} — falling back to iloc")
            f["adx"] = adx_df.iloc[:, 0]
    else:
        f["adx"] = 0.0

    # -----------------------------------------------------------------------
    # 5. Momentum oscillators
    # -----------------------------------------------------------------------
    # RSI
    f["rsi_14"] = ta.rsi(f["close"], length=14)
    f["rsi_7"]  = ta.rsi(f["close"], length=7)

    # RSI zone flags (useful binary features for ML)
    f["rsi_overbought"]  = (f["rsi_14"] > 70).astype(int)
    f["rsi_oversold"]    = (f["rsi_14"] < 30).astype(int)

    # Stochastic — name-based column extraction
    stoch_df = ta.stoch(f["high"], f["low"], f["close"], k=14, d=3)
    if stoch_df is not None and not stoch_df.empty:
        cols = list(stoch_df.columns)
        k_col = next((c for c in cols if "STOCHk" in c or c.startswith("K")), None)
        d_col = next((c for c in cols if "STOCHd" in c or c.startswith("D")), None)
        if k_col and d_col:
            f["stoch_k"] = stoch_df[k_col]
            f["stoch_d"] = stoch_df[d_col]
        else:
            logger.warning(f"Stoch columns unexpected: {cols} — falling back to iloc")
            f["stoch_k"] = stoch_df.iloc[:, 0]
            f["stoch_d"] = stoch_df.iloc[:, min(1, len(cols)-1)]
    else:
        f["stoch_k"] = f["stoch_d"] = 50.0

    # Williams %R
    f["williams_r"] = ta.willr(f["high"], f["low"], f["close"], length=14)

    # -----------------------------------------------------------------------
    # 6. Volatility bands
    # -----------------------------------------------------------------------
    # Bollinger Bands — name-based column extraction
    bb_df = ta.bbands(f["close"], length=20, std=2)
    if bb_df is not None and not bb_df.empty:
        cols = list(bb_df.columns)
        # BBU = upper, BBM = mid, BBL = lower
        upper_col = next((c for c in cols if "BBU" in c), None)
        mid_col   = next((c for c in cols if "BBM" in c), None)
        lower_col = next((c for c in cols if "BBL" in c), None)
        if upper_col and mid_col and lower_col:
            f["bb_upper"] = bb_df[upper_col]
            f["bb_mid"]   = bb_df[mid_col]
            f["bb_lower"] = bb_df[lower_col]
        else:
            logger.warning(f"BB columns unexpected: {cols} — falling back to iloc")
            f["bb_upper"] = bb_df.iloc[:, 0]
            f["bb_mid"]   = bb_df.iloc[:, min(1, len(cols)-1)]
            f["bb_lower"] = bb_df.iloc[:, min(2, len(cols)-1)]
        f["bb_width"]    = (f["bb_upper"] - f["bb_lower"]) / f["bb_mid"]
        f["bb_position"] = (f["close"] - f["bb_lower"]) / (f["bb_upper"] - f["bb_lower"] + 1e-9)
    else:
        f["bb_width"] = f["bb_position"] = 0.5

    # -----------------------------------------------------------------------
    # 7. Volume features
    # -----------------------------------------------------------------------
    f["volume_ma_20"]    = f["volume"].rolling(20).mean()
    f["volume_ratio"]    = f["volume"] / (f["volume_ma_20"] + 1e-9)  # >1 = high volume day
    f["volume_spike"]    = (f["volume_ratio"] > 2.0).astype(int)     # 2x average = spike

    # OBV — on-balance volume (cumulative buying/selling pressure)
    f["obv"] = ta.obv(f["close"], f["volume"])
    f["obv_ma_20"] = f["obv"].rolling(20).mean()
    f["obv_above_ma"] = (f["obv"] > f["obv_ma_20"]).astype(int)

    # VWAP deviation (close vs volume-weighted avg price over 20 days)
    vwap = (f["close"] * f["volume"]).rolling(20).sum() / f["volume"].rolling(20).sum()
    f["vwap_deviation"] = (f["close"] - vwap) / vwap

    # -----------------------------------------------------------------------
    # 8. Market regime features
    # (used by ensemble to weight models appropriately)
    # -----------------------------------------------------------------------
    # Trending: ADX > 25 and EMA alignment
    f["is_trending"] = (
        (f["adx"] > 25) &
        (f["ema9_above_ema21"] == f["ema21_above_ema50"])  # all EMAs aligned
    ).astype(int)

    # High volatility: ATR% in top quartile of recent history
    atr_threshold = f["atr_pct"].rolling(60).quantile(0.75)
    f["is_high_volatility"] = (f["atr_pct"] > atr_threshold).astype(int)

    # -----------------------------------------------------------------------
    # 9. Clean up
    # -----------------------------------------------------------------------
    # Drop raw OHLCV cols that models don’t need directly
    # (models use derived features, not raw prices — avoids scale issues)
    feature_cols = [c for c in f.columns if c not in ["open", "high", "low", "volume"]]
    f = f[feature_cols]

    # Drop rows with NaN (from rolling window warmup period)
    f = f.dropna()

    if f.empty:
        logger.warning("All rows dropped after NaN removal — need more historical data")
        return None

    logger.info(f"Computed {len(f.columns)} features, {len(f)} valid rows")
    return f


def get_latest_features(df: pd.DataFrame) -> Optional[dict]:
    """
    Returns features for the single most recent candle as a flat dict.
    This is what gets passed to AI models at inference time.
    """
    features_df = compute_features(df)
    if features_df is None or features_df.empty:
        return None

    latest = features_df.iloc[-1].to_dict()

    # Replace any remaining NaN/inf with 0.0 — models can’t handle these
    for key, val in latest.items():
        if not isinstance(val, (int, float)) or np.isnan(val) or np.isinf(val):
            latest[key] = 0.0

    return latest


def detect_market_regime(df: pd.DataFrame) -> str:
    """
    Classifies current market as 'trending', 'ranging', or 'volatile'.
    Used by ensemble layer to select appropriate model weights.
    """
    features = get_latest_features(df)
    if features is None:
        return "ranging"  # safe default

    adx       = features.get("adx", 0)
    high_vol  = features.get("is_high_volatility", 0)
    trending  = features.get("is_trending", 0)

    if high_vol == 1:
        return "volatile"
    if trending == 1 and adx > 25:
        return "trending"
    return "ranging"
