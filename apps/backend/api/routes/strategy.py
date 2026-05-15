# api/routes/strategy.py
import os
import logging
from fastapi import APIRouter, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/strategy", tags=["strategy"])

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def verify_key(key: str = Security(api_key_header)):
    if key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


@router.get("/tune")
async def get_tune_suggestions(
    _: str = Security(verify_key),
):
    """
    Analyze signal_outcome data and suggest strategy parameter adjustments.
    Advisory only — does not apply changes automatically.
    """
    from services.strategy.auto_tuner import analyze_and_suggest
    result = await analyze_and_suggest()
    return {
        "sufficient_data":  result.sufficient_data,
        "sample_count":     result.sample_count,
        "current_params":   result.current_params,
        "suggested_params": result.suggested_params,
        "changes":          result.changes,
        "reasoning":        result.reasoning,
        "confidence":       result.confidence,
        "skip_reason":      result.skip_reason,
    }


@router.post("/tune/apply")
async def apply_tune_suggestions(
    _: str = Security(verify_key),
):
    """
    Apply the current auto-tuner suggestions at runtime.
    Changes persist until next container restart.
    Commit risk_manager.py to make them permanent.
    """
    from services.strategy.auto_tuner import analyze_and_suggest, apply_suggestions
    result = await analyze_and_suggest()
    if not result.sufficient_data:
        return {"applied": False, "reason": result.skip_reason}
    if not result.changes:
        return {"applied": False, "reason": "No changes suggested"}
    applied = await apply_suggestions(result.suggested_params)
    return {
        "applied":  True,
        "changes":  applied,
        "warning":  "Changes are runtime-only. Update risk_manager.py to make permanent.",
    }
