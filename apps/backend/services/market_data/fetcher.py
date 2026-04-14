# services/market_data/fetcher.py
# Responsible for downloading OHLCV data from yfinance.
# This is the ONLY place in the codebase that talks to yfinance directly.
# Everything else calls these functions.
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

def to_yf_symbol(symbol: str) -> str:
    """
    Convert internal symbol format to yfinance format.
    Internal: 'NSE:RELIANCE'  -> yfinance: 'RELIANCE.NS'
    Internal: 'BSE:INFY'      -> yfinance: 'INFY.BO'
    Internal: 'CRYPTO:BTC'    -> yfinance: 'BTC-USD'
    Internal: 'FOREX:USDINR'  -> yfinance: 'USDINR=X'
    """
    if ":" not in symbol:
        return symbol  # already in yfinance format

    exchange, ticker = symbol.split(":", 1)
    exchange = exchange.upper()

    if exchange == "NSE":
        return f"{ticker}.NS"
    elif exchange == "BSE":
        return f"{ticker}.BO"
    elif exchange == "CRYPTO":
        return f"{ticker}-USD"
    elif exchange == "FOREX":
        return f"{ticker}=X"
    else:
        return ticker


# ---------------------------------------------------------------------------
# Historical OHLCV
# ---------------------------------------------------------------------------

def fetch_historical(
    symbol: str,
    period_days: int = 730,
    interval: str = "1d",
) -> Optional[pd.DataFrame]:
    """
    Download historical OHLCV for a symbol.

    Args:
        symbol:      Internal symbol e.g. 'NSE:RELIANCE'
        period_days: How many days of history to fetch
        interval:    Candle size — '1d' for daily, '1h' for hourly, '5m' for 5-min

    Returns:
        DataFrame with columns [Open, High, Low, Close, Volume]
        or None if download fails.

    Note: yfinance has a 15-minute delay on NSE data.
    Intraday intervals (< 1d) only available for last 60 days.
    """
    yf_symbol = to_yf_symbol(symbol)
    end = datetime.utcnow()
    start = end - timedelta(days=period_days)

    try:
        df = yf.download(
            yf_symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
            auto_adjust=True,   # adjusts for splits and dividends
        )

        if df.empty:
            logger.warning(f"No data returned for {symbol} ({yf_symbol})")
            return None

        # Flatten MultiIndex columns yfinance sometimes returns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Standardise column names
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })

        df = df["open high low close volume".split()].copy()
        df.index.name = "datetime"
        # Only drop rows where close price is missing — volume NaN is acceptable
        df = df.dropna(subset=["close"])
        df["volume"] = df["volume"].fillna(0)

        logger.info(f"Fetched {len(df)} rows for {symbol} interval={interval}")
        return df

    except Exception as e:
        logger.error(f"Failed to fetch {symbol}: {e}")
        return None


def fetch_latest_price(symbol: str) -> Optional[float]:
    """
    Get the most recent closing price for a symbol.
    Used for real-time unrealized P&L calculation.
    Returns None if fetch fails.
    """
    df = fetch_historical(symbol, period_days=5, interval="1d")
    if df is None or df.empty:
        return None
    return float(df["close"].iloc[-1])


def fetch_batch_latest_prices(symbols: list[str]) -> dict[str, Optional[float]]:
    """
    Fetch latest prices for multiple symbols efficiently.
    Returns {symbol: price} dict. Failed fetches return None for that symbol.
    """
    results = {}
    yf_symbols = [to_yf_symbol(s) for s in symbols]
    symbol_map = dict(zip(yf_symbols, symbols))  # yf_symbol -> internal symbol

    try:
        tickers = yf.download(
            " ".join(yf_symbols),
            period="2d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )

        if isinstance(tickers.columns, pd.MultiIndex):
            close_prices = tickers["Close"]
        else:
            close_prices = tickers[["Close"]].rename(
                columns={"Close": yf_symbols[0]}
            )

        for yf_sym, internal_sym in symbol_map.items():
            try:
                results[internal_sym] = float(close_prices[yf_sym].dropna().iloc[-1])
            except Exception:
                results[internal_sym] = None

    except Exception as e:
        logger.error(f"Batch price fetch failed: {e}")
        for sym in symbols:
            results[sym] = None

    return results
