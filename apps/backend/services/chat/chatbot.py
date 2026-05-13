# services/chat/chatbot.py
# Explainability chatbot with RAG — retrieves real trade/signal data
# from DB and uses it as LLM context. Never invents data.
import logging
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AlgoTrade's AI assistant — an expert at explaining what the automated trading system did and why.

Your job:
- Explain trade decisions using the ACTUAL data provided in context
- Answer questions about portfolio performance, losses, wins, signals
- Never invent numbers, prices, or outcomes — only use provided data
- Be direct and specific: name the stock, the price, the reason

Tone: concise, factual, like a senior quant explaining to a junior trader.
Format: short paragraphs, no bullet overload, max 250 words.
Always end with: "This is paper trading — for educational purposes only."
"""


class Chatbot:
    async def respond(
        self,
        message: str,
        db: AsyncSession,
        conversation_history: list[dict] = None,
    ) -> dict:
        history = conversation_history or []

        # RAG: retrieve relevant context from DB
        from services.chat.rag_retriever import retrieve_context
        context = await retrieve_context(message, db)

        # Build prompt with retrieved context
        user_prompt = self._build_prompt(message, context)

        # Call LLM
        reply = await self._call_llm(user_prompt, history)

        return {
            "reply":        reply,
            "context_used": context.get("type", "general"),
            "signal_id":    None,
        }

    def _build_prompt(self, message: str, context: dict) -> str:
        ctx_type = context.get("type", "general")
        ctx_json = json.dumps(context, indent=2, default=str)

        if ctx_type == "general":
            return (
                f"Question: {message}\n\n"
                f"Answer based on your trading knowledge. Be concise."
            )

        if ctx_type == "stock_deep_dive":
            symbol = context.get("symbol", "")
            trades = context.get("trade_history", [])
            signal = context.get("latest_signal") or {}
            return (
                f"Question: {message}\n\n"
                f"Data for {symbol}:\n{ctx_json}\n\n"
                f"Using ONLY the data above: explain what happened with {symbol}. "
                f"Cover: signal direction ({signal.get('action','?')} at "
                f"{signal.get('confidence','?')} confidence), "
                f"trade outcomes ({len(trades)} trades found), "
                f"exit reasons, and what the models (RL, transformer, sentiment) indicated. "
                f"If there were losses, explain why based on the data."
            )

        if ctx_type == "trade_history":
            summary = context.get("summary", {})
            return (
                f"Question: {message}\n\n"
                f"Trade history data:\n{ctx_json}\n\n"
                f"Summarise the recent trading performance: "
                f"{summary.get('total_trades',0)} trades, "
                f"{summary.get('win_rate',0)}% win rate, "
                f"₹{summary.get('total_pnl',0)} total P&L. "
                f"Explain patterns, what worked, what didn't."
            )

        if ctx_type == "loss_analysis":
            worst = context.get("worst_trade") or {}
            return (
                f"Question: {message}\n\n"
                f"Loss data:\n{ctx_json}\n\n"
                f"Analyse the losing trades. Focus on: which exit reasons caused the most losses, "
                f"worst trade was {worst.get('symbol','?')} at {worst.get('pnl_pct','?')}%, "
                f"and what patterns explain the losses."
            )

        if ctx_type == "portfolio":
            return (
                f"Question: {message}\n\n"
                f"Current portfolio:\n{ctx_json}\n\n"
                f"Answer the question using only this portfolio data. "
                f"Be specific about numbers."
            )

        if ctx_type == "performance":
            return (
                f"Question: {message}\n\n"
                f"Performance data:\n{ctx_json}\n\n"
                f"Analyse the system's trading performance. Cover win rate, P&L, "
                f"which market regimes worked best, and what needs improvement."
            )

        if ctx_type == "reports":
            return (
                f"Question: {message}\n\n"
                f"Recent daily reports:\n{ctx_json}\n\n"
                f"Summarise what the system reported. Use the actual narrative content."
            )

        # Fallback
        return (
            f"Question: {message}\n\n"
            f"Context:\n{ctx_json}\n\n"
            f"Answer using the provided context only."
        )

    async def _call_llm(self, user_prompt: str, history: list[dict]) -> str:
        from core.config import settings
        import httpx

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-6:],
            {"role": "user", "content": user_prompt},
        ]

        # Try Groq first
        if settings.GROQ_API_KEY and settings.GROQ_API_KEY not in ('', 'PASTE_YOUR_NEW_KEY_HERE'):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        f"{settings.GROQ_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                        json={
                            "model":       settings.GROQ_MODEL,
                            "messages":    messages,
                            "max_tokens":  500,
                            "temperature": 0.2,
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"Groq failed: {e}")

        # Fallback: Ollama
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                flat = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model":  settings.OLLAMA_MODEL,
                        "prompt": flat + "\nASSISTANT:",
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 500},
                    },
                )
                resp.raise_for_status()
                return resp.json().get("response", "").strip()
        except Exception as e:
            logger.warning(f"Ollama failed: {e}")

        return (
            "The AI service is temporarily unavailable. "
            "This is paper trading — for educational purposes only."
        )


_chatbot: Optional[Chatbot] = None

def get_chatbot() -> Chatbot:
    global _chatbot
    if _chatbot is None:
        _chatbot = Chatbot()
    return _chatbot
