# services/market_data/fundamentals.py
# Piotroski F-Score implementation for NSE stocks.
# Score 0-9: each criterion adds 1 point.
# F-Score >= 7: fundamentally strong (BUY filter)
# F-Score <= 3: fundamentally weak (SKIP)
# F-Score 4-6: neutral (let technical signals decide)
import logging
from typing import Optional
from functools import lru_cache
from datetime import datetime, timedelta
import yfinance as yf

from services.market_data.fetcher import to_yf_symbol

logger = logging.getLogger(__name__)

# Cache TTL: fundamentals change quarterly, cache for 24 hours
_cache: dict[str, dict] = {}
_CACHE_HOURS = 24


def get_fscore(symbol: str) -> dict:
    """
    Compute Piotroski F-Score for a stock.

    Returns:
        {
          'fscore':      int (0-9),
          'grade':       'strong' | 'neutral' | 'weak',
          'criteria':    dict of all 9 criteria with bool values,
          'pass_filter': bool (True if F-Score >= 6),
          'source':      'live' | 'cache' | 'unavailable',
        }
    """
    # Check cache
    if symbol in _cache:
        cached = _cache[symbol]
        age_hours = (datetime.utcnow() - cached['fetched_at']).total_seconds() / 3600
        if age_hours < _CACHE_HOURS:
            return {**cached['result'], 'source': 'cache'}

    try:
        result = _compute_fscore(symbol)
        _cache[symbol] = {'result': result, 'fetched_at': datetime.utcnow()}
        return {**result, 'source': 'live'}
    except Exception as e:
        logger.warning(f"F-Score computation failed for {symbol}: {e}")
        return _unavailable(symbol)


def _compute_fscore(symbol: str) -> dict:
    """Fetch financials and compute all 9 Piotroski criteria."""
    yf_sym = to_yf_symbol(symbol)
    ticker = yf.Ticker(yf_sym)

    # Fetch financial statements
    try:
        income   = ticker.financials          # Annual income statement
        balance  = ticker.balance_sheet       # Annual balance sheet
        cashflow = ticker.cashflow            # Annual cash flow statement
    except Exception as e:
        raise ValueError(f"Could not fetch financials: {e}")

    if income is None or income.empty:
        raise ValueError("Empty income statement")
    if balance is None or balance.empty:
        raise ValueError("Empty balance sheet")

    # Helper to safely get a value from a DataFrame
    def get(df, *keys):
        """Try multiple key names — yfinance field names vary."""
        for key in keys:
            if key in df.index:
                vals = df.loc[key].dropna()
                if len(vals) >= 1:
                    return float(vals.iloc[0])  # most recent year
        return None

    def get_prev(df, *keys):
        """Get previous year value."""
        for key in keys:
            if key in df.index:
                vals = df.loc[key].dropna()
                if len(vals) >= 2:
                    return float(vals.iloc[1])  # previous year
        return None

    # ── Extract financials ──────────────────────────────────────────────
    # Profitability
    net_income      = get(income,  'Net Income', 'NetIncome')
    total_assets    = get(balance, 'Total Assets', 'TotalAssets')
    total_assets_py = get_prev(balance, 'Total Assets', 'TotalAssets')
    operating_cf    = get(cashflow, 'Operating Cash Flow', 'Total Cash From Operating Activities')
    roa             = (net_income / total_assets) if net_income and total_assets else None
    roa_py          = None

    # Try to compute prior year ROA
    net_income_py = get_prev(income, 'Net Income', 'NetIncome')
    if net_income_py and total_assets_py:
        roa_py = net_income_py / total_assets_py

    # Leverage / Liquidity
    long_term_debt      = get(balance, 'Long Term Debt', 'LongTermDebt')
    long_term_debt_py   = get_prev(balance, 'Long Term Debt', 'LongTermDebt')
    current_assets      = get(balance, 'Current Assets', 'Total Current Assets', 'CurrentAssets')
    current_assets_py   = get_prev(balance, 'Current Assets', 'Total Current Assets', 'CurrentAssets')
    current_liabilities = get(balance, 'Current Liabilities', 'Total Current Liabilities', 'CurrentLiabilities')
    current_liab_py     = get_prev(balance, 'Current Liabilities', 'Total Current Liabilities', 'CurrentLiabilities')
    shares_outstanding  = get(balance, 'Common Stock', 'Share Issued', 'Ordinary Shares Number')
    shares_outstanding_py = get_prev(balance, 'Common Stock', 'Share Issued', 'Ordinary Shares Number')

    current_ratio    = (current_assets / current_liabilities) if current_assets and current_liabilities else None
    current_ratio_py = (current_assets_py / current_liab_py)  if current_assets_py and current_liab_py else None
    leverage         = (long_term_debt / total_assets)    if long_term_debt    and total_assets    else None
    leverage_py      = (long_term_debt_py / total_assets_py) if long_term_debt_py and total_assets_py else None

    # Operating efficiency
    revenue      = get(income, 'Total Revenue', 'Revenue')
    revenue_py   = get_prev(income, 'Total Revenue', 'Revenue')
    gross_profit = get(income, 'Gross Profit', 'GrossProfit')
    gross_profit_py = get_prev(income, 'Gross Profit', 'GrossProfit')

    gross_margin    = (gross_profit / revenue)       if gross_profit    and revenue    else None
    gross_margin_py = (gross_profit_py / revenue_py) if gross_profit_py and revenue_py else None
    asset_turnover    = (revenue / total_assets)       if revenue    and total_assets    else None
    asset_turnover_py = (revenue_py / total_assets_py) if revenue_py and total_assets_py else None
    accruals = ((net_income - operating_cf) / total_assets) if net_income and operating_cf and total_assets else None

    # ── Score each criterion ────────────────────────────────────────────
    criteria = {}

    # PROFITABILITY (4 criteria)
    # F1: ROA positive
    criteria['roa_positive']       = bool(roa and roa > 0)
    # F2: Operating cash flow positive
    criteria['ocf_positive']       = bool(operating_cf and operating_cf > 0)
    # F3: ROA improving year-over-year
    criteria['roa_improving']      = bool(roa and roa_py and roa > roa_py)
    # F4: Accruals (cash flow > net income / assets = quality earnings)
    criteria['low_accruals']       = bool(accruals is not None and accruals < 0)

    # LEVERAGE / LIQUIDITY (3 criteria)
    # F5: Leverage decreasing (less debt relative to assets)
    criteria['leverage_decreasing'] = bool(
        leverage is not None and leverage_py is not None and leverage < leverage_py
    )
    # F6: Current ratio improving (more liquid)
    criteria['liquidity_improving'] = bool(
        current_ratio is not None and current_ratio_py is not None
        and current_ratio > current_ratio_py
    )
    # F7: No dilution (shares not increased)
    criteria['no_dilution']         = bool(
        shares_outstanding is not None and shares_outstanding_py is not None
        and shares_outstanding <= shares_outstanding_py * 1.01  # allow 1% tolerance
    )

    # OPERATING EFFICIENCY (2 criteria)
    # F8: Gross margin improving
    criteria['margin_improving']    = bool(
        gross_margin is not None and gross_margin_py is not None
        and gross_margin > gross_margin_py
    )
    # F9: Asset turnover improving (more revenue per unit of assets)
    criteria['turnover_improving']  = bool(
        asset_turnover is not None and asset_turnover_py is not None
        and asset_turnover > asset_turnover_py
    )

    fscore = sum(1 for v in criteria.values() if v)

    if fscore >= 7:   grade = 'strong'
    elif fscore <= 3: grade = 'weak'
    else:             grade = 'neutral'

    # pass_filter: allow neutral and strong through
    # Only block fundamentally weak stocks (F-Score <= 3)
    pass_filter = fscore >= 4

    logger.info(
        f"F-Score {symbol}: {fscore}/9 ({grade}) "
        f"[ROA:{criteria['roa_positive']} OCF:{criteria['ocf_positive']} "
        f"Lever:{criteria['leverage_decreasing']} Margin:{criteria['margin_improving']}]"
    )

    return {
        'fscore':      fscore,
        'grade':       grade,
        'criteria':    criteria,
        'pass_filter': pass_filter,
    }


def _unavailable(symbol: str) -> dict:
    """Return when financial data is unavailable."""
    return {
        'fscore':      5,   # neutral — don't block if data unavailable
        'grade':       'neutral',
        'criteria':    {},
        'pass_filter': True,   # pass through if no data
        'source':      'unavailable',
    }


def clear_fscore_cache() -> None:
    """Clear cache — call at start of each trading day."""
    global _cache
    _cache = {}
    logger.info("F-Score cache cleared")
