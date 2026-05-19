# services/market_data/fetcher.py
# Downloads OHLCV data for NSE stocks.
# Primary: NseIndiaApi (works from cloud/datacenter IPs via HTTP/2)
# Fallback: yfinance (works from residential IPs)
import pandas as pd
import time
from datetime import datetime, timedelta, date
from typing import Optional
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory OHLCV cache — avoids repeated downloads during the same session
# TTL: 6 hours for daily data (market data doesn't change intraday)
# ---------------------------------------------------------------------------
import time as _time

_OHLCV_CACHE: dict = {}   # symbol -> (df, timestamp)
_OHLCV_TTL   = 6 * 3600   # 6 hours
_PRICE_CACHE: dict = {}   # symbol -> (price, timestamp)
_PRICE_TTL   = 30          # 30 seconds (used by real-time monitor)


def _cache_get(cache: dict, key: str, ttl: int):
    entry = cache.get(key)
    if entry and (_time.time() - entry[1]) < ttl:
        return entry[0]
    return None


def _cache_set(cache: dict, key: str, value):
    cache[key] = (value, _time.time())

# NseIndia session — singleton
_nse: Optional[object] = None
_nse_dir = tempfile.mkdtemp(prefix='nse_')


def _get_nse():
    global _nse
    if _nse is None:
        try:
            from nse import NSE
            _nse = NSE(_nse_dir, server=True)
            logger.info("NseIndiaApi initialised (server mode)")
        except Exception as e:
            logger.warning(f"NseIndiaApi init failed: {e}")
    return _nse


def to_yf_symbol(symbol: str) -> str:
    if ":" not in symbol:
        return symbol
    exchange, ticker = symbol.split(":", 1)
    exchange = exchange.upper()
    if exchange == "NSE":   return f"{ticker}.NS"
    elif exchange == "BSE": return f"{ticker}.BO"
    else: return ticker


def _nse_ticker(symbol: str) -> str:
    if ":" in symbol:
        return symbol.split(":", 1)[1]
    return symbol


def _fetch_nse_historical(symbol: str, period_days: int = 730) -> Optional[pd.DataFrame]:
    """
    Fetch historical OHLCV from NSE India via NseIndiaApi.
    Works from datacenter/cloud IPs.
    """
    if not symbol.startswith("NSE:"):
        return None

    ticker = _nse_ticker(symbol)
    nse    = _get_nse()
    if nse is None:
        return None

    end_date   = date.today()
    start_date = end_date - timedelta(days=min(period_days, 730))

    try:
        data = nse.fetch_equity_historical_data(
            ticker,
            from_date=start_date,
            to_date=end_date,
        )

        if data is None or (hasattr(data, '__len__') and len(data) == 0):
            logger.warning(f"NSE: no history for {symbol}")
            return None

        rows = []
        for item in data:
            try:
                rows.append({
                    'datetime': pd.to_datetime(item['mtimestamp'], dayfirst=True),
                    'open':     float(item['chOpeningPrice']),
                    'high':     float(item['chTradeHighPrice']),
                    'low':      float(item['chTradeLowPrice']),
                    'close':    float(item['chClosingPrice']),
                    'volume':   float(item['chTotTradedQty']),
                })
            except Exception:
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.set_index('datetime').sort_index()
        df = df.dropna(subset=['close'])
        df['volume'] = df['volume'].fillna(0)

        logger.info(f"NSE: {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        logger.warning(f"NSE history failed for {symbol}: {e}")
        return None


def _fetch_yfinance_historical(symbol: str, period_days: int, interval: str) -> Optional[pd.DataFrame]:
    """Fallback: yfinance (works on residential IPs)."""
    try:
        import yfinance as yf
        yf_symbol = to_yf_symbol(symbol)
        end   = datetime.utcnow()
        start = end - timedelta(days=period_days)
        df = yf.download(
            yf_symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Open": "open", "High": "high",
                                 "Low": "low", "Close": "close", "Volume": "volume"})
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index.name = "datetime"
        df = df.dropna(subset=["close"])
        df["volume"] = df["volume"].fillna(0)
        logger.info(f"yfinance: {len(df)} rows for {symbol}")
        return df
    except Exception as e:
        logger.error(f"yfinance fetch failed for {symbol}: {e}")
        return None


def fetch_historical(
    symbol: str,
    period_days: int = 500,
    interval: str = "1d",
) -> Optional[pd.DataFrame]:
    """
    Download historical OHLCV.
    Caches results for 6 hours to avoid repeated yfinance/NSE calls.
    Tries NseIndiaApi first (cloud-compatible), falls back to yfinance.
    """
    cache_key = f"{symbol}:{period_days}:{interval}"
    cached = _cache_get(_OHLCV_CACHE, cache_key, _OHLCV_TTL)
    if cached is not None:
        logger.debug(f"Cache hit: {symbol} ({len(cached)} rows)")
        return cached

    df = None
    if symbol.startswith("NSE:") and interval == "1d":
        df = _fetch_nse_historical(symbol, period_days)
        if df is not None and len(df) >= 30:
            _cache_set(_OHLCV_CACHE, cache_key, df)
            return df
        _time.sleep(0.3)

    df = _fetch_yfinance_historical(symbol, period_days, interval)
    if df is not None:
        _cache_set(_OHLCV_CACHE, cache_key, df)
    return df


def fetch_latest_price(symbol: str) -> Optional[float]:
    """Get most recent price using NSE quote API. Cached for 30 seconds."""
    cached = _cache_get(_PRICE_CACHE, symbol, _PRICE_TTL)
    if cached is not None:
        return cached

    price = None
    if symbol.startswith("NSE:"):
        ticker = _nse_ticker(symbol)
        nse    = _get_nse()
        if nse:
            try:
                data  = nse.quote(ticker)
                p     = data.get("priceInfo", {}).get("lastPrice")
                if p:
                    price = float(p)
            except Exception as e:
                logger.warning(f"NSE quote failed for {symbol}: {e}")

    if price is None:
        df = fetch_historical(symbol, period_days=5, interval="1d")
        if df is not None and not df.empty:
            price = float(df["close"].iloc[-1])

    if price is not None:
        _cache_set(_PRICE_CACHE, symbol, price)
    return price


def fetch_batch_latest_prices(symbols: list[str]) -> dict[str, Optional[float]]:
    """Fetch latest prices for multiple symbols."""
    results = {}
    for symbol in symbols:
        results[symbol] = fetch_latest_price(symbol)
        time.sleep(0.1)
    return results
