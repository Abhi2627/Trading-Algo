# api/routes/chat.py
import os
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from core.database import get_db
from services.chat.chatbot import get_chatbot

router = APIRouter(prefix="/chat", tags=["chat"])
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def verify_key(key: str = Security(api_key_header)):
    if key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


class ChatRequest(BaseModel):
    message:              str
    conversation_history: list[dict] = []


@router.post("/")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Send a message to the explainability chatbot.

    The chatbot automatically detects whether you're asking about:
    - A specific signal/stock  → fetches audit record and explains the decision
    - Your portfolio           → fetches wallet state and summarises
    - General trading concepts → answers from knowledge base

    Pass conversation_history as [{"role": "user"|"assistant", "content": "..."}]
    for multi-turn conversations.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    result = await get_chatbot().respond(
        message=request.message.strip(),
        db=db,
        conversation_history=request.conversation_history,
    )
    return result


@router.get("/explain/{signal_id}")
async def explain_signal(
    signal_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Security(verify_key),
):
    """
    Direct signal explanation by signal ID.
    Returns a plain-English explanation of exactly why that signal was generated.
    """
    from sqlalchemy import select
    from core.models import Signal, Asset

    result = await db.execute(
        select(Signal, Asset)
        .join(Asset, Signal.asset_id == Asset.id)
        .where(Signal.id == signal_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")

    signal, asset = row
    chatbot = get_chatbot()
    context = chatbot._build_signal_context(signal, asset)
    prompt  = chatbot._build_user_prompt(
        f"Explain the {signal.action.value} signal for {asset.name}",
        context,
    )
    reply = await chatbot._call_llm(prompt, [])

    return {
        "signal_id":  signal_id,
        "symbol":     asset.symbol,
        "action":     signal.action.value,
        "confidence": signal.confidence,
        "explanation":reply,
        "context":    context,
    }
