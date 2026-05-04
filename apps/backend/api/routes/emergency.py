# api/routes/emergency.py
# Emergency liquidation and bank account linking endpoints.
import os
from fastapi import APIRouter, Depends, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from core.database import get_db
from services.wallet.emergency_service import get_emergency_service

router = APIRouter(prefix="/emergency", tags=["emergency"])
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_key(key: str = Security(api_key_header)):
    if key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


class LiquidateRequest(BaseModel):
    amount_needed: float
    reason: str = "emergency withdrawal"


class LinkBankRequest(BaseModel):
    bank_name:    str
    account_no:   str
    ifsc:         str
    account_name: str


@router.post("/preview")
async def preview_liquidation(
    request: LiquidateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Preview which stocks would be sold to raise the required amount.
    Does NOT execute any trades. Use this first to see the plan.

    Example: I need ₹5,000 urgently.
    Response shows: wallet has ₹500, would sell ONGC (losing) and SBIN (near stop)
    to raise ₹4,500, keeping HDFCBANK (strong trend) intact.
    """
    if request.amount_needed <= 0:
        raise HTTPException(status_code=422, detail="amount_needed must be positive")
    return await get_emergency_service().get_liquidation_preview(db, request.amount_needed)


@router.post("/liquidate")
async def emergency_liquidate(
    request: LiquidateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    EXECUTE emergency liquidation — sells minimum stocks to raise required amount.

    Smart sell order:
    1. Positions near stop-loss (would be auto-sold soon anyway)
    2. Positions with negative P&L (already losing)
    3. Lowest-potential positions (smallest upside)
    4. Best-performing positions (last resort only)

    After selling, cash lands in wallet immediately.
    If bank account is linked, shows transfer details.
    """
    if request.amount_needed <= 0:
        raise HTTPException(status_code=422, detail="amount_needed must be positive")
    result = await get_emergency_service().emergency_liquidate(
        db, request.amount_needed, request.reason
    )
    await db.commit()
    return result


@router.post("/link-bank")
async def link_bank_account(
    request: LinkBankRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Link your bank account for direct transfer on emergency liquidation.

    In paper trading: details stored, no actual transfer.
    In live trading (Zerodha): used to route withdrawals directly to your bank.

    Only last 4 digits of account number are stored visibly.
    """
    return await get_emergency_service().link_bank_account(
        db,
        bank_name=request.bank_name,
        account_no=request.account_no,
        ifsc=request.ifsc,
        account_name=request.account_name,
    )


@router.get("/bank-status")
async def bank_status(
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """Check if a bank account is linked."""
    svc  = get_emergency_service()
    bank = await svc._get_linked_bank(db)
    if bank:
        return {
            "linked":       True,
            "bank_name":    bank["bank_name"],
            "account_last4":bank["account_last4"],
            "ifsc":         bank["ifsc"],
            "account_name": bank["account_name"],
        }
    return {
        "linked":  False,
        "message": "No bank account linked. Use POST /emergency/link-bank to add one."
    }
