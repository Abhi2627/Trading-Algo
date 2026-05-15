# services/market_data/intraday_fetcher.py
# Fetches 5-minute OHLCV data for intraday strategy.
# Uses yfinance as primary (NSE API doesn't support sub-daily intervals).
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def fetch_5min(symbol: str, days: int = 5) -> Optional[pd.DataFrame]:
    """
    Fetch 5-minute OHLCV for the last `days` trading days.
    Returns DataFrame with columns: open, high, low, close, volume
    Index: datetime (UTC)
    """
    try:
        import yfinance as yf
        from services.market_data.fetcher import to_yf_symbol
        yf_sym = to_yf_symbol(symbol)
        end    = datetime.utcnow()
        start  = end - timedelta(days=days)
        df = yf.download(
            yf_sym,
            start    = start.strftime("%Y-%m-%d"),
            end      = end.strftime("%Y-%m-%d"),
            interval = "5m",
            progress = False,
            auto_adjust = True,
        )
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={
            "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume"
        })
        df = df[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
        df["volume"] = df["volume"].fillna(0)
        df.index.name = "datetime"
        return df
    except Exception as e:
        logger.warning(f"5min fetch failed for {symbol}: {e}")
        return None


def compute_intraday_features(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Compute intraday features on 5-min OHLCV.
    Returns enriched DataFrame with VWAP, RSI, momentum cols.
    """
    if df is None or len(df) < 20:
        return None

    df = df.copy()

    # VWAP — cumulative within each trading day
    df["date"]        = df.index.date
    df["typical"]     = (df["high"] + df["low"] + df["close"]) / 3
    df["cum_tv"]      = df.groupby("date").apply(
        lambda g: (g["typical"] * g["volume"]).cumsum()
    ).reset_index(level=0, drop=True)
    df["cum_vol"]     = df.groupby("date")["volume"].cumsum()
    df["vwap"]        = df["cum_tv"] / df["cum_vol"].replace(0, float("nan"))

    # Price vs VWAP
    df["close_vs_vwap"] = (df["close"] - df["vwap"]) / df["vwap"]

    # RSI(14) on 5-min closes
    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=14, adjust=False).mean()
    avg_loss = loss.ewm(span=14, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi"] = 100 - (100 / (1 + rs))

    # Momentum: 5-bar and 15-bar
    df["mom_5"]  = df["close"].pct_change(5)
    df["mom_15"] = df["close"].pct_change(15)

    # Volume spike: current volume vs 20-bar average
    df["vol_avg"]   = df["volume"].rolling(20).mean()
    df["vol_spike"] = df["volume"] / df["vol_avg"].replace(0, float("nan"))

    # EMA9 and EMA21 crossover
    df["ema9"]       = df["close"].ewm(span=9, adjust=False).mean()
    df["ema21"]      = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_cross"]  = df["ema9"] - df["ema21"]

    # ATR(14) on 5-min bars for stop sizing
    df["prev_close"] = df["close"].shift(1)
    df["tr"]         = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["prev_close"]).abs(),
        (df["low"]  - df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    df["atr"]        = df["tr"].ewm(span=14, adjust=False).mean()

    return df.drop(columns=["date", "typical", "cum_tv", "cum_vol",
                             "prev_close", "tr", "vol_avg"], errors="ignore")
