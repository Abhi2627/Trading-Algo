# test/test_market_data.py — Phase 2 tests
# Tests fetcher, features, and assets route.
# Run: pytest test/test_market_data.py -v
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_ohlcv(rows: int = 300) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing (no network needed)."""
    np.random.seed(42)
    close = 2800 + np.cumsum(np.random.randn(rows) * 20)
    close = np.maximum(close, 100)  # never negative
    df = pd.DataFrame({
        "open":   close * (1 + np.random.randn(rows) * 0.002),
        "high":   close * (1 + np.abs(np.random.randn(rows)) * 0.005),
        "low":    close * (1 - np.abs(np.random.randn(rows)) * 0.005),
        "close":  close,
        "volume": np.random.randint(500_000, 5_000_000, rows).astype(float),
    })
    df.index = pd.date_range(end="2024-12-31", periods=rows, freq="B")
    df.index.name = "datetime"
    return df


# ---------------------------------------------------------------------------
# Fetcher tests
# ---------------------------------------------------------------------------

def test_to_yf_symbol_nse():
    from services.market_data.fetcher import to_yf_symbol
    assert to_yf_symbol("NSE:RELIANCE") == "RELIANCE.NS"

def test_to_yf_symbol_bse():
    from services.market_data.fetcher import to_yf_symbol
    assert to_yf_symbol("BSE:INFY") == "INFY.BO"

def test_to_yf_symbol_crypto():
    from services.market_data.fetcher import to_yf_symbol
    assert to_yf_symbol("CRYPTO:BTC") == "BTC-USD"

def test_to_yf_symbol_forex():
    from services.market_data.fetcher import to_yf_symbol
    assert to_yf_symbol("FOREX:USDINR") == "USDINR=X"

def test_to_yf_symbol_passthrough():
    """Symbols without exchange prefix pass through unchanged."""
    from services.market_data.fetcher import to_yf_symbol
    assert to_yf_symbol("RELIANCE.NS") == "RELIANCE.NS"


# ---------------------------------------------------------------------------
# Feature tests (use synthetic data — no network)
# ---------------------------------------------------------------------------

def test_compute_features_returns_dataframe():
    from services.market_data.features import compute_features
    df = make_ohlcv(300)
    result = compute_features(df)
    assert result is not None
    assert isinstance(result, pd.DataFrame)
    assert len(result) > 0

def test_compute_features_minimum_columns():
    """Key features must always be present in output."""
    from services.market_data.features import compute_features
    df = make_ohlcv(300)
    result = compute_features(df)
    required = [
        "close", "return_1d", "rsi_14", "macd_line",
        "ema_50", "bb_width", "volume_ratio", "adx",
        "is_trending", "is_high_volatility",
    ]
    for col in required:
        assert col in result.columns, f"Missing column: {col}"

def test_compute_features_no_nan_in_last_row():
    """The last row (inference input) must have no NaN values."""
    from services.market_data.features import compute_features
    df = make_ohlcv(300)
    result = compute_features(df)
    last_row = result.iloc[-1]
    nan_cols = last_row[last_row.isna()].index.tolist()
    assert nan_cols == [], f"NaN found in last row: {nan_cols}"

def test_compute_features_too_short_returns_none():
    """Less than 60 rows must return None."""
    from services.market_data.features import compute_features
    df = make_ohlcv(50)
    result = compute_features(df)
    assert result is None

def test_rsi_range():
    """RSI must always be between 0 and 100."""
    from services.market_data.features import compute_features
    df = make_ohlcv(300)
    result = compute_features(df)
    assert result["rsi_14"].between(0, 100).all()

def test_volume_ratio_positive():
    """Volume ratio must always be non-negative."""
    from services.market_data.features import compute_features
    df = make_ohlcv(300)
    result = compute_features(df)
    assert (result["volume_ratio"] >= 0).all()

def test_get_latest_features_returns_dict():
    from services.market_data.features import get_latest_features
    df = make_ohlcv(300)
    features = get_latest_features(df)
    assert features is not None
    assert isinstance(features, dict)
    assert "rsi_14" in features
    assert "close" in features

def test_get_latest_features_no_nan_values():
    """No NaN or inf values in latest features dict."""
    from services.market_data.features import get_latest_features
    df = make_ohlcv(300)
    features = get_latest_features(df)
    for key, val in features.items():
        assert not (isinstance(val, float) and (np.isnan(val) or np.isinf(val))), \
            f"Bad value for {key}: {val}"

def test_detect_market_regime_valid_output():
    """Market regime must be one of three valid values."""
    from services.market_data.features import detect_market_regime
    df = make_ohlcv(300)
    regime = detect_market_regime(df)
    assert regime in ("trending", "ranging", "volatile")


# ---------------------------------------------------------------------------
# Assets seeder test (uses in-memory mock — no DB needed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_assets_count():
    """Seeder must attempt to insert the correct number of assets."""
    from services.market_data.assets import (
        NIFTY_50_EQUITIES, CRYPTO_ASSETS, FOREX_PAIRS
    )
    total = len(NIFTY_50_EQUITIES) + len(CRYPTO_ASSETS) + len(FOREX_PAIRS)
    assert total == 27  # 20 equities + 4 crypto + 3 forex

def test_asset_symbols_no_duplicates():
    """All asset symbols must be unique."""
    from services.market_data.assets import (
        NIFTY_50_EQUITIES, CRYPTO_ASSETS, FOREX_PAIRS
    )
    all_symbols = (
        [s for s, _ in NIFTY_50_EQUITIES] +
        [s for s, _ in CRYPTO_ASSETS] +
        [s for s, _ in FOREX_PAIRS]
    )
    assert len(all_symbols) == len(set(all_symbols)), "Duplicate symbols found"

def test_asset_symbols_correct_format():
    """All symbols must follow EXCHANGE:TICKER format."""
    from services.market_data.assets import (
        NIFTY_50_EQUITIES, CRYPTO_ASSETS, FOREX_PAIRS
    )
    all_symbols = (
        [s for s, _ in NIFTY_50_EQUITIES] +
        [s for s, _ in CRYPTO_ASSETS] +
        [s for s, _ in FOREX_PAIRS]
    )
    for sym in all_symbols:
        assert ":" in sym, f"Symbol missing exchange prefix: {sym}"
        exchange, ticker = sym.split(":", 1)
        assert len(exchange) > 0 and len(ticker) > 0
