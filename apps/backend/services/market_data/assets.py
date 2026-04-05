# services/market_data/assets.py
# Seeds the Asset table with all tracked symbols.
# Run once on first startup. Safe to re-run (upsert logic).
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.models import Asset, AssetType
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Master symbol list
# Internal format: EXCHANGE:TICKER
# ---------------------------------------------------------------------------

NIFTY_50_EQUITIES = [
    ("NSE:RELIANCE",     "Reliance Industries"),
    ("NSE:TCS",          "Tata Consultancy Services"),
    ("NSE:HDFCBANK",     "HDFC Bank"),
    ("NSE:INFY",         "Infosys"),
    ("NSE:ICICIBANK",    "ICICI Bank"),
    ("NSE:HINDUNILVR",   "Hindustan Unilever"),
    ("NSE:ITC",          "ITC Limited"),
    ("NSE:SBIN",         "State Bank of India"),
    ("NSE:BHARTIARTL",   "Bharti Airtel"),
    ("NSE:KOTAKBANK",    "Kotak Mahindra Bank"),
    ("NSE:LT",           "Larsen & Toubro"),
    ("NSE:AXISBANK",     "Axis Bank"),
    ("NSE:ASIANPAINT",   "Asian Paints"),
    ("NSE:MARUTI",       "Maruti Suzuki"),
    ("NSE:SUNPHARMA",    "Sun Pharmaceutical"),
    ("NSE:TITAN",        "Titan Company"),
    ("NSE:BAJFINANCE",   "Bajaj Finance"),
    ("NSE:WIPRO",        "Wipro"),
    ("NSE:ONGC",         "Oil and Natural Gas Corp"),
    ("NSE:ULTRACEMCO",   "UltraTech Cement"),
]

CRYPTO_ASSETS = [
    ("CRYPTO:BTC",   "Bitcoin"),
    ("CRYPTO:ETH",   "Ethereum"),
    ("CRYPTO:SOL",   "Solana"),
    ("CRYPTO:BNB",   "BNB"),
]

FOREX_PAIRS = [
    ("FOREX:USDINR",  "US Dollar / Indian Rupee"),
    ("FOREX:EURINR",  "Euro / Indian Rupee"),
    ("FOREX:EURUSD",  "Euro / US Dollar"),
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

    asset_definitions = [
        *[(sym, name, "NSE",    AssetType.equity)      for sym, name in NIFTY_50_EQUITIES],
        *[(sym, name, "CRYPTO", AssetType.crypto)      for sym, name in CRYPTO_ASSETS],
        *[(sym, name, "FOREX",  AssetType.forex)       for sym, name in FOREX_PAIRS],
    ]

    for symbol, name, exchange, asset_type in asset_definitions:
        # Check if already exists
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
    """
    Returns list of active symbol strings, optionally filtered by asset type.
    Used by data ingestion workers to know what to fetch.
    """
    query = select(Asset.symbol).where(Asset.is_active == True)  # noqa: E712
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)

    result = await db.execute(query)
    return [row[0] for row in result.fetchall()]
