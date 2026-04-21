# services/news/news_fetcher.py
import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional
import httpx
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    # Economic Times — Markets (primary)
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    # Economic Times — Earnings & Results
    "https://economictimes.indiatimes.com/markets/earnings/rssfeeds/2143429.cms",
    # MoneyControl
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://www.moneycontrol.com/rss/marketreports.xml",
    # Business Standard
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.business-standard.com/rss/companies-101.rss",
    # Mint
    "https://www.livemint.com/rss/companies",
    "https://www.livemint.com/rss/markets",
]

TICKER_KEYWORDS: dict[str, list[str]] = {
    'RELIANCE':   ['reliance', 'ril', 'jio', 'mukesh ambani'],
    'TCS':        ['tcs', 'tata consultancy'],
    'HDFCBANK':   ['hdfc bank'],
    'INFY':       ['infosys', 'infy'],
    'ICICIBANK':  ['icici bank', 'icici'],
    'SBIN':       ['sbi', 'state bank'],
    'BHARTIARTL': ['airtel', 'bharti'],
    'KOTAKBANK':  ['kotak'],
    'LT':         ['larsen', 'l&t'],
    'AXISBANK':   ['axis bank'],
    'WIPRO':      ['wipro'],
    'HCLTECH':    ['hcl tech', 'hcltech'],
    'TECHM':      ['tech mahindra'],
    'BAJFINANCE': ['bajaj finance'],
    'BAJAJFINSV': ['bajaj finserv'],
    'MARUTI':     ['maruti'],
    'TATAMOTORS': ['tata motors'],
    'SUNPHARMA':  ['sun pharma', 'sun pharmaceutical'],
    'DRREDDY':    ['dr reddy'],
    'CIPLA':      ['cipla'],
    'DIVISLAB':   ['divi'],
    'ONGC':       ['ongc', 'oil and natural gas'],
    'ADANIENT':   ['adani enterprises', 'adani group'],
    'ADANIPORTS': ['adani ports'],
    'NTPC':       ['ntpc'],
    'POWERGRID':  ['power grid'],
    'ITC':        ['itc limited', 'itc ltd'],
    'HINDUNILVR': ['hindustan unilever', 'hul'],
    'ASIANPAINT': ['asian paints'],
    'TITAN':      ['titan company'],
    'JSWSTEEL':   ['jsw steel'],
    'TATASTEEL':  ['tata steel'],
    'ULTRACEMCO': ['ultratech cement'],
    'NESTLEIND':  ['nestle india'],
    'EICHERMOT':  ['eicher motors'],
    'HEROMOTOCO': ['hero motocorp'],
    'HINDALCO':   ['hindalco'],
    'INDUSINDBK': ['indusind bank'],
    'APOLLOHOSP': ['apollo hospitals'],
    'BPCL':       ['bpcl', 'bharat petroleum'],
    'BRITANNIA':  ['britannia'],
    'COALINDIA':  ['coal india'],
    'SBILIFE':    ['sbi life'],
    'HDFCLIFE':   ['hdfc life'],
    'LUPIN':      ['lupin'],
    'BIOCON':     ['biocon'],
    'BANKBARODA': ['bank of baroda'],
    'INDIGO':     ['indigo', 'interglobe'],
    'DLF':        ['dlf'],
    'HAVELLS':    ['havells'],
    'MARICO':     ['marico'],
    'DABUR':      ['dabur'],
    'COLPAL':     ['colgate'],
    'MUTHOOTFIN': ['muthoot'],
    'SIEMENS':    ['siemens india'],
    'PIDILITIND': ['pidilite'],
    'GRASIM':     ['grasim'],
    'TATACONSUM': ['tata consumer'],
    'FEDERALBNK': ['federal bank'],
    'IDFCFIRSTB': ['idfc first'],
    'BANDHANBNK': ['bandhan bank'],
    'ASHOKLEY':   ['ashok leyland'],
    'TVSMOTOR':   ['tvs motor'],
    'AUROPHARMA': ['aurobindo pharma'],
    'TORNTPHARM': ['torrent pharma'],
    'ALKEM':      ['alkem'],
    'MPHASIS':    ['mphasis'],
    'LTIM':       ['ltimindtree'],
    'COFORGE':    ['coforge'],
    'PERSISTENT': ['persistent systems'],
    'M&M':        ['mahindra'],
}

MARKET_KEYWORDS = [
    'nifty', 'sensex', 'rbi', 'sebi', 'india market',
    'nse', 'bse', 'rate cut', 'inflation', 'gdp india',
    'fii', 'dii', 'rupee', 'budget',
]

CACHE_TTL_MINUTES = 30

_global_headlines:  list[dict]          = []
_global_fetched_at: Optional[datetime]  = None
_symbol_cache:      dict[str, dict]     = {}


async def fetch_global_headlines() -> list[dict]:
    global _global_headlines, _global_fetched_at
    if _global_fetched_at is not None:
        age = (datetime.now(timezone.utc) - _global_fetched_at).total_seconds() / 60
        if age < CACHE_TTL_MINUTES:
            return _global_headlines

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        results = await asyncio.gather(
            *[_fetch_feed(client, url) for url in RSS_FEEDS],
            return_exceptions=True,
        )

    all_items: list[dict] = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)

    seen: set[str] = set()
    unique: list[dict] = []
    for item in all_items:
        key = hashlib.md5(item['title'].lower().encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    _global_headlines  = unique
    _global_fetched_at = datetime.now(timezone.utc)
    logger.info(f"News: {len(unique)} headlines from {len(RSS_FEEDS)} feeds")
    return unique


async def get_headlines_for_symbol(symbol: str, max_headlines: int = 8) -> list[str]:
    if symbol in _symbol_cache:
        age = (datetime.now(timezone.utc) - _symbol_cache[symbol]['fetched_at']).total_seconds() / 60
        if age < CACHE_TTL_MINUTES:
            return _symbol_cache[symbol]['headlines']

    all_headlines = await fetch_global_headlines()
    ticker = symbol.split(':')[-1].upper()

    keywords = list(TICKER_KEYWORDS.get(ticker, []))
    # Only add raw ticker if it's long enough to avoid false positives
    # e.g. 'ril' matches 'April', 'tcs' matches 'stocks' — skip short tickers
    if len(ticker) >= 5 and ticker.lower() not in [k.lower() for k in keywords]:
        keywords.insert(0, ticker.lower())

    matched: list[str] = []
    for item in all_headlines:
        title_lower = item['title'].lower()
        for kw in keywords:
            # Use word-boundary matching: keyword must be surrounded by
            # non-alphanumeric chars (spaces, punctuation, start/end of string)
            pattern = r'(?<![a-z0-9])' + re.escape(kw.lower()) + r'(?![a-z0-9])'
            if re.search(pattern, title_lower):
                matched.append(item['title'])
                break
        if len(matched) >= max_headlines:
            break

    # Only pad with market headlines if we have zero stock-specific news
    # Don't pad if we have even 1 genuine match — avoids noise
    if len(matched) == 0:
        for item in all_headlines[:20]:
            if item['title'] not in matched:
                title_lower = item['title'].lower()
                if any(kw in title_lower for kw in MARKET_KEYWORDS):
                    matched.append(item['title'])
                    if len(matched) >= 5:  # max 5 fallback headlines
                        break

    result = matched[:max_headlines]
    _symbol_cache[symbol] = {'headlines': result, 'fetched_at': datetime.now(timezone.utc)}
    logger.debug(f"News: {symbol} -> {len(result)} headlines ({len(matched)} matched)")
    return result


async def _fetch_feed(client: httpx.AsyncClient, url: str) -> list[dict]:
    try:
        resp = await client.get(url, headers={'User-Agent': 'Mozilla/5.0 (AlgoTrade/1.0)'})
        resp.raise_for_status()
        root  = ET.fromstring(resp.text)
        items: list[dict] = []
        for item in root.findall('.//item')[:30]:
            title_el = item.find('title')
            if title_el is None or not title_el.text:
                continue
            title = _clean(title_el.text)
            if len(title) < 15:
                continue
            pub_el = item.find('pubDate')
            items.append({
                'title':        title,
                'published_at': pub_el.text if pub_el is not None else '',
                'source':       _source_name(url),
            })
        return items
    except ET.ParseError:
        return await _fetch_atom(client, url)
    except Exception as e:
        logger.warning(f"RSS failed ({_source_name(url)}): {e}")
        return []


async def _fetch_atom(client: httpx.AsyncClient, url: str) -> list[dict]:
    try:
        resp = await client.get(url)
        root = ET.fromstring(resp.text)
        ns   = {'a': 'http://www.w3.org/2005/Atom'}
        items: list[dict] = []
        for entry in root.findall('a:entry', ns)[:20]:
            title_el = entry.find('a:title', ns)
            if title_el is None or not title_el.text:
                continue
            items.append({'title': _clean(title_el.text), 'published_at': '', 'source': _source_name(url)})
        return items
    except Exception:
        return []


def _clean(text: str) -> str:
    text = re.sub(r'<!\[CDATA\[|\]\]>', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _source_name(url: str) -> str:
    if 'economictimes' in url:     return 'Economic Times'
    if 'moneycontrol'  in url:     return 'MoneyControl'
    if 'business-standard' in url: return 'Business Standard'
    if 'livemint'      in url:     return 'Mint'
    return url.split('/')[2] if '//' in url else url


def clear_cache() -> None:
    global _global_headlines, _global_fetched_at, _symbol_cache
    _global_headlines  = []
    _global_fetched_at = None
    _symbol_cache      = {}
    logger.info("News cache cleared")
