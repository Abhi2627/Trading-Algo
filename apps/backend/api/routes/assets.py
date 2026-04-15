# api/routes/assets.py
# Endpoints for querying assets and their latest market data + features.
from fastapi import APIRouter, Depends, HTTPException, Security, Query
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import os

from core.database import get_db
from core.models import Asset, AssetType
from services.market_data.fetcher import fetch_historical, fetch_latest_price
from services.market_data.features import get_latest_features, detect_market_regime
from services.market_data.assets import seed_assets, get_active_symbols

router = APIRouter(prefix="/assets", tags=["assets"])

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def verify_key(key: str = Security(api_key_header)):
    if key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


@router.get("/sections")
async def list_sections(
    _: str = Security(verify_key),
):
    """
    Returns all market sections with their constituent symbols.
    Used by frontend to render grouped watchlists.
    """
    from services.market_data.assets import SECTIONS
    return {
        "sections": [
            {
                "id":     section_id,
                "label":  label,
                "count":  len(symbols),
                "symbols": [sym for sym, _ in symbols],
            }
            for section_id, label, symbols in SECTIONS
        ]
    }


# ---------------------------------------------------------------------------
# GET /assets
# ---------------------------------------------------------------------------

@router.get("/")
async def list_assets(
    asset_type: Optional[str] = Query(None, description="Filter: equity | crypto | forex | mutual_fund"),
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    List all tracked assets. Optionally filter by type.
    """
    query = select(Asset)
    if active_only:
        query = query.where(Asset.is_active == True)  # noqa: E712
    if asset_type:
        try:
            at = AssetType[asset_type]
            query = query.where(Asset.asset_type == at)
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid asset_type '{asset_type}'. Choose from: equity, crypto, forex, mutual_fund"
            )

    result = await db.execute(query.order_by(Asset.symbol))
    assets = result.scalars().all()

    return {
        "count": len(assets),
        "assets": [
            {
                "symbol": a.symbol,
                "name": a.name,
                "exchange": a.exchange,
                "asset_type": a.asset_type.value,
                "is_active": a.is_active,
            }
            for a in assets
        ]
    }


# ---------------------------------------------------------------------------
# GET /assets/{symbol}/price
# ---------------------------------------------------------------------------

@router.get("/{symbol}/price")
async def get_price(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Get the latest closing price for a symbol.
    symbol format: NSE:RELIANCE, CRYPTO:BTC, FOREX:USDINR
    """
    # Verify asset exists in DB
    result = await db.execute(select(Asset).where(Asset.symbol == symbol.upper()))
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")

    price = fetch_latest_price(symbol.upper())
    if price is None:
        raise HTTPException(status_code=503, detail=f"Could not fetch price for '{symbol}'")

    return {
        "symbol": symbol.upper(),
        "name": asset.name,
        "price": round(price, 2),
        "currency": "INR" if asset.exchange in ("NSE", "BSE") else "USD",
    }


# ---------------------------------------------------------------------------
# GET /assets/{symbol}/features
# ---------------------------------------------------------------------------

@router.get("/{symbol}/features")
async def get_features(
    symbol: str,
    period_days: int = Query(365, ge=60, le=1825, description="History to compute features over"),
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Fetch OHLCV history and return the latest computed feature vector.
    This is the exact input that AI models receive at inference time.
    """
    result = await db.execute(select(Asset).where(Asset.symbol == symbol.upper()))
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")

    df = fetch_historical(symbol.upper(), period_days=period_days)
    if df is None:
        raise HTTPException(status_code=503, detail=f"Could not fetch OHLCV for '{symbol}'")

    features = get_latest_features(df)
    if features is None:
        raise HTTPException(
            status_code=422,
            detail=f"Not enough data to compute features for '{symbol}' (need 60+ candles)"
        )

    regime = detect_market_regime(df)

    return {
        "symbol": symbol.upper(),
        "name": asset.name,
        "market_regime": regime,
        "feature_count": len(features),
        "features": features,
    }


# ---------------------------------------------------------------------------
# POST /assets/seed  (admin — run once)
# ---------------------------------------------------------------------------

@router.post("/seed")
async def seed(
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Seeds the database with all tracked assets.
    Safe to call multiple times — skips existing entries.
    """
    inserted = await seed_assets(db)
    return {"message": f"Seeding complete. {inserted} new assets inserted."}
