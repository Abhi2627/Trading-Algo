# services/market_data/fetcher.py
# Downloads OHLCV data for NSE stocks.
# Primary: NSE India API (works from datacenter IPs)
# Fallback: yfinance (works from residential IPs)
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# NSE session — reuse for all requests
_nse_session: Optional[requests.Session] = None

def _get_nse_session() -> requests.Session:
    global _nse_session
    if _nse_session is None:
        _nse_session = requests.Session()
        _nse_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.nseindia.com/',
            'Connection': 'keep-alive',
        })
        # Warm up session with homepage visit
        try:
            _nse_session.get('https://www.nseindia.com', timeout=10)
        except Exception:
            pass
    return _nse_session


def to_yf_symbol(symbol: str) -> str:
    if ":" not in symbol:
        return symbol
    exchange, ticker = symbol.split(":", 1)
    exchange = exchange.upper()
    if exchange == "NSE":   return f"{ticker}.NS"
    elif exchange == "BSE": return f"{ticker}.BO"
    else: return ticker


def _nse_ticker(symbol: str) -> str:
    """Extract NSE ticker from internal symbol."""
    if ":" in symbol:
        return symbol.split(":", 1)[1]
    return symbol


def _fetch_nse_historical(symbol: str, period_days: int = 730) -> Optional[pd.DataFrame]:
    """
    Fetch historical OHLCV from NSE India API.
    NSE provides up to 2 years of daily data.
    """
    ticker = _nse_ticker(symbol)
    if not symbol.startswith("NSE:"):
        return None

    session  = _get_nse_session()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=min(period_days, 730))

    url = (
        f"https://www.nseindia.com/api/historical/cm/equity"
        f"?symbol={ticker}"
        f"&series=[%22EQ%22]"
        f"&from={start_date.strftime('%d-%m-%Y')}"
        f"&to={end_date.strftime('%d-%m-%Y')}"
        f"&csv=true"
    )

    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()

        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))

        if df.empty:
            return None

        # NSE column names vary — handle both formats
        col_map = {}
        for col in df.columns:
            cl = col.strip().lower()
            if 'date' in cl:   col_map[col] = 'datetime'
            elif cl in ('open',):  col_map[col] = 'open'
            elif cl in ('high',):  col_map[col] = 'high'
            elif cl in ('low',):   col_map[col] = 'low'
            elif 'close' in cl and 'prev' not in cl: col_map[col] = 'close'
            elif 'volume' in cl or 'trdqty' in cl:  col_map[col] = 'volume'

        df = df.rename(columns=col_map)
        needed = ['datetime', 'open', 'high', 'low', 'close', 'volume']
        missing = [c for c in needed if c not in df.columns]
        if missing:
            logger.warning(f"NSE data missing columns {missing} for {symbol}")
            return None

        df = df[needed].copy()
        df['datetime'] = pd.to_datetime(df['datetime'], dayfirst=True)
        df = df.set_index('datetime').sort_index()

        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', ''), errors='coerce'
            )

        df = df.dropna(subset=['close'])
        df['volume'] = df['volume'].fillna(0)

        logger.info(f"NSE API: {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        logger.warning(f"NSE historical fetch failed for {symbol}: {e}")
        return None


def _fetch_yfinance_historical(symbol: str, period_days: int, interval: str) -> Optional[pd.DataFrame]:
    """Fallback: fetch from yfinance (works on residential IPs)."""
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
    period_days: int = 730,
    interval: str = "1d",
) -> Optional[pd.DataFrame]:
    """
    Download historical OHLCV. Tries NSE API first, falls back to yfinance.
    """
    # Try NSE API first (works from datacenter IPs)
    if symbol.startswith("NSE:") and interval == "1d":
        df = _fetch_nse_historical(symbol, period_days)
        if df is not None and len(df) >= 60:
            return df
        time.sleep(0.5)  # Rate limit protection

    # Fallback to yfinance
    return _fetch_yfinance_historical(symbol, period_days, interval)


def fetch_latest_price(symbol: str) -> Optional[float]:
    """
    Get most recent price. Uses NSE quote API for real-time data.
    """
    # Try NSE quote API first
    if symbol.startswith("NSE:"):
        ticker = _nse_ticker(symbol)
        try:
            session = _get_nse_session()
            resp = session.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={ticker}",
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            price = data.get("priceInfo", {}).get("lastPrice")
            if price:
                return float(price)
        except Exception as e:
            logger.warning(f"NSE quote failed for {symbol}: {e}")

    # Fallback: get from historical
    df = fetch_historical(symbol, period_days=5, interval="1d")
    if df is not None and not df.empty:
        return float(df["close"].iloc[-1])
    return None


def fetch_batch_latest_prices(symbols: list[str]) -> dict[str, Optional[float]]:
    """Fetch latest prices for multiple symbols."""
    results = {}
    for symbol in symbols:
        results[symbol] = fetch_latest_price(symbol)
        time.sleep(0.1)  # Avoid rate limiting
    return results
