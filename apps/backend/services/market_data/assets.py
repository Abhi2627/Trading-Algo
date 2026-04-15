# services/market_data/assets.py
# Seeds the Asset table with all tracked symbols.
# Run once on first startup. Safe to re-run (upsert logic).
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.models import Asset, AssetType
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Master symbol list — focused on Indian markets
# Internal format: EXCHANGE:TICKER
# ---------------------------------------------------------------------------

# Nifty 50 — Large cap index (NSE)
NIFTY_50 = [
    ("NSE:RELIANCE",   "Reliance Industries"),
    ("NSE:TCS",        "Tata Consultancy Services"),
    ("NSE:HDFCBANK",   "HDFC Bank"),
    ("NSE:INFY",       "Infosys"),
    ("NSE:ICICIBANK",  "ICICI Bank"),
    ("NSE:HINDUNILVR", "Hindustan Unilever"),
    ("NSE:ITC",        "ITC Limited"),
    ("NSE:SBIN",       "State Bank of India"),
    ("NSE:BHARTIARTL", "Bharti Airtel"),
    ("NSE:KOTAKBANK",  "Kotak Mahindra Bank"),
    ("NSE:LT",         "Larsen & Toubro"),
    ("NSE:AXISBANK",   "Axis Bank"),
    ("NSE:ASIANPAINT", "Asian Paints"),
    ("NSE:MARUTI",     "Maruti Suzuki"),
    ("NSE:SUNPHARMA",  "Sun Pharmaceutical"),
    ("NSE:TITAN",      "Titan Company"),
    ("NSE:BAJFINANCE", "Bajaj Finance"),
    ("NSE:WIPRO",      "Wipro"),
    ("NSE:ONGC",       "Oil and Natural Gas Corp"),
    ("NSE:ULTRACEMCO", "UltraTech Cement"),
    ("NSE:NESTLEIND",  "Nestle India"),
    ("NSE:ADANIENT",   "Adani Enterprises"),
    ("NSE:ADANIPORTS", "Adani Ports"),
    ("NSE:POWERGRID",  "Power Grid Corp"),
    ("NSE:NTPC",       "NTPC"),
    ("NSE:TECHM",      "Tech Mahindra"),
    ("NSE:HCLTECH",    "HCL Technologies"),
    ("NSE:BAJAJFINSV", "Bajaj Finserv"),
    ("NSE:JSWSTEEL",   "JSW Steel"),
    ("NSE:TATAMOTORS", "Tata Motors"),
    ("NSE:TATACONSUM", "Tata Consumer Products"),
    ("NSE:TATASTEEL",  "Tata Steel"),
    ("NSE:GRASIM",     "Grasim Industries"),
    ("NSE:DIVISLAB",   "Divi's Laboratories"),
    ("NSE:DRREDDY",    "Dr. Reddy's Laboratories"),
    ("NSE:EICHERMOT",  "Eicher Motors"),
    ("NSE:HEROMOTOCO", "Hero MotoCorp"),
    ("NSE:HINDALCO",   "Hindalco Industries"),
    ("NSE:INDUSINDBK", "IndusInd Bank"),
    ("NSE:M&M",        "Mahindra & Mahindra"),
    ("NSE:APOLLOHOSP", "Apollo Hospitals"),
    ("NSE:BPCL",       "Bharat Petroleum"),
    ("NSE:BRITANNIA",  "Britannia Industries"),
    ("NSE:CIPLA",      "Cipla"),
    ("NSE:COALINDIA",  "Coal India"),
    ("NSE:SBILIFE",    "SBI Life Insurance"),
    ("NSE:HDFCLIFE",   "HDFC Life Insurance"),
    ("NSE:BAJAJ-AUTO", "Bajaj Auto"),
    ("NSE:UPL",        "UPL"),
    ("NSE:SHREECEM",   "Shree Cement"),
]

# Nifty Next 50 — Mid-large cap (selected liquid ones)
NIFTY_NEXT_50 = [
    ("NSE:SIEMENS",    "Siemens India"),
    ("NSE:GODREJCP",   "Godrej Consumer Products"),
    ("NSE:PIDILITIND", "Pidilite Industries"),
    ("NSE:MUTHOOTFIN", "Muthoot Finance"),
    ("NSE:LUPIN",      "Lupin"),
    ("NSE:BIOCON",     "Biocon"),
    ("NSE:BANKBARODA", "Bank of Baroda"),
    ("NSE:PNB",        "Punjab National Bank"),
    ("NSE:CANBK",      "Canara Bank"),
    ("NSE:INDIGO",     "IndiGo (InterGlobe Aviation)"),
    ("NSE:DLF",        "DLF"),
    ("NSE:HAVELLS",    "Havells India"),
    ("NSE:MARICO",     "Marico"),
    ("NSE:DABUR",      "Dabur India"),
    ("NSE:COLPAL",     "Colgate-Palmolive India"),
]

# Nifty Bank — Banking sector index
NIFTY_BANK = [
    ("NSE:HDFCBANK",   "HDFC Bank"),
    ("NSE:ICICIBANK",  "ICICI Bank"),
    ("NSE:KOTAKBANK",  "Kotak Mahindra Bank"),
    ("NSE:AXISBANK",   "Axis Bank"),
    ("NSE:SBIN",       "State Bank of India"),
    ("NSE:INDUSINDBK", "IndusInd Bank"),
    ("NSE:BANKBARODA", "Bank of Baroda"),
    ("NSE:PNB",        "Punjab National Bank"),
    ("NSE:CANBK",      "Canara Bank"),
    ("NSE:FEDERALBNK", "Federal Bank"),
    ("NSE:IDFCFIRSTB", "IDFC First Bank"),
    ("NSE:BANDHANBNK", "Bandhan Bank"),
]

# Nifty IT — Technology sector
NIFTY_IT = [
    ("NSE:TCS",       "Tata Consultancy Services"),
    ("NSE:INFY",      "Infosys"),
    ("NSE:WIPRO",     "Wipro"),
    ("NSE:HCLTECH",   "HCL Technologies"),
    ("NSE:TECHM",     "Tech Mahindra"),
    ("NSE:MPHASIS",   "Mphasis"),
    ("NSE:LTIM",      "LTIMindtree"),
    ("NSE:COFORGE",   "Coforge"),
    ("NSE:PERSISTENT","Persistent Systems"),
]

# Nifty Pharma — Healthcare and pharma
NIFTY_PHARMA = [
    ("NSE:SUNPHARMA", "Sun Pharmaceutical"),
    ("NSE:DRREDDY",   "Dr. Reddy's Laboratories"),
    ("NSE:CIPLA",     "Cipla"),
    ("NSE:DIVISLAB",  "Divi's Laboratories"),
    ("NSE:BIOCON",    "Biocon"),
    ("NSE:LUPIN",     "Lupin"),
    ("NSE:AUROPHARMA","Aurobindo Pharma"),
    ("NSE:TORNTPHARM","Torrent Pharmaceuticals"),
    ("NSE:ALKEM",     "Alkem Laboratories"),
]

# Nifty Auto — Automobile sector
NIFTY_AUTO = [
    ("NSE:MARUTI",     "Maruti Suzuki"),
    ("NSE:TATAMOTORS", "Tata Motors"),
    ("NSE:M&M",        "Mahindra & Mahindra"),
    ("NSE:BAJAJ-AUTO", "Bajaj Auto"),
    ("NSE:HEROMOTOCO", "Hero MotoCorp"),
    ("NSE:EICHERMOT",  "Eicher Motors"),
    ("NSE:ASHOKLEY",   "Ashok Leyland"),
    ("NSE:TVSMOTOR",   "TVS Motor Company"),
    ("NSE:BOSCHLTD",   "Bosch"),
]

# Sensex 30 — BSE flagship index (BSE listed)
SENSEX_30 = [
    ("BSE:RELIANCE",   "Reliance Industries"),
    ("BSE:TCS",        "Tata Consultancy Services"),
    ("BSE:HDFCBANK",   "HDFC Bank"),
    ("BSE:INFY",       "Infosys"),
    ("BSE:ICICIBANK",  "ICICI Bank"),
    ("BSE:HINDUNILVR", "Hindustan Unilever"),
    ("BSE:ITC",        "ITC Limited"),
    ("BSE:SBIN",       "State Bank of India"),
    ("BSE:BHARTIARTL", "Bharti Airtel"),
    ("BSE:KOTAKBANK",  "Kotak Mahindra Bank"),
    ("BSE:LT",         "Larsen & Toubro"),
    ("BSE:AXISBANK",   "Axis Bank"),
    ("BSE:ASIANPAINT", "Asian Paints"),
    ("BSE:MARUTI",     "Maruti Suzuki"),
    ("BSE:SUNPHARMA",  "Sun Pharmaceutical"),
    ("BSE:TITAN",      "Titan Company"),
    ("BSE:BAJFINANCE", "Bajaj Finance"),
    ("BSE:WIPRO",      "Wipro"),
    ("BSE:ONGC",       "Oil and Natural Gas Corp"),
    ("BSE:ULTRACEMCO", "UltraTech Cement"),
    ("BSE:NESTLEIND",  "Nestle India"),
    ("BSE:POWERGRID",  "Power Grid Corp"),
    ("BSE:NTPC",       "NTPC"),
    ("BSE:TECHM",      "Tech Mahindra"),
    ("BSE:HCLTECH",    "HCL Technologies"),
    ("BSE:BAJAJFINSV", "Bajaj Finserv"),
    ("BSE:JSWSTEEL",   "JSW Steel"),
    ("BSE:TATAMOTORS", "Tata Motors"),
    ("BSE:TATACONSUM", "Tata Consumer Products"),
    ("BSE:TATASTEEL",  "Tata Steel"),
]

# ---------------------------------------------------------------------------
# Section metadata — maps section_id to display label + symbols
# Used by the frontend to group assets in the Signals screen
# ---------------------------------------------------------------------------

SECTIONS = [
    ("nifty_50",       "Nifty 50",        NIFTY_50),
    ("nifty_next_50",  "Nifty Next 50",   NIFTY_NEXT_50),
    ("nifty_bank",     "Nifty Bank",      NIFTY_BANK),
    ("nifty_it",       "Nifty IT",        NIFTY_IT),
    ("nifty_pharma",   "Nifty Pharma",    NIFTY_PHARMA),
    ("nifty_auto",     "Nifty Auto",      NIFTY_AUTO),
    ("sensex_30",      "BSE Sensex 30",   SENSEX_30),
]


# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------

async def seed_assets(db: AsyncSession) -> int:
    """
    Inserts all assets into the database.
    Skips symbols that already exist (safe to re-run).
    Returns the count of newly inserted assets.
    """
    inserted = 0

    # Collect unique symbols across all sections (avoid duplicates)
    seen = set()
    asset_definitions = []
    for _, _, symbols in SECTIONS:
        exchange = "BSE" if symbols and symbols[0][0].startswith("BSE:") else "NSE"
        for sym, name in symbols:
            if sym not in seen:
                seen.add(sym)
                exch = sym.split(":")[0]
                asset_definitions.append((sym, name, exch, AssetType.equity))

    for symbol, name, exchange, asset_type in asset_definitions:
        result = await db.execute(select(Asset).where(Asset.symbol == symbol))
        existing = result.scalar_one_or_none()

        if existing is None:
            asset = Asset(
                symbol=symbol,
                name=name,
                exchange=exchange,
                asset_type=asset_type,
                is_active=True,
            )
            db.add(asset)
            inserted += 1
            logger.info(f"Seeded asset: {symbol}")
        else:
            logger.debug(f"Asset already exists, skipping: {symbol}")

    await db.flush()
    logger.info(f"Asset seeding complete. Inserted {inserted} new assets.")
    return inserted


async def get_active_symbols(
    db: AsyncSession,
    asset_type: AssetType = None,
) -> list[str]:
    query = select(Asset.symbol).where(Asset.is_active == True)  # noqa: E712
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    result = await db.execute(query)
    return [row[0] for row in result.fetchall()]

