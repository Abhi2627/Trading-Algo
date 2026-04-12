# services/chat/chatbot.py
# Explainability chatbot. Reads signal audit records from DB and
# generates plain-English explanations via LLM.
# The LLM never invents data — it only narrates what the system computed.
import logging
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from core.models import Signal, Asset, Trade, TradeStatus

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a trading assistant.

Rules:
- Provide clear, structured responses.
- Be concise and practical.
- Do not give financial advice.
- Never invent or fabricate data. Only use provided or known information.
- Always include risk considerations.
- Always end with: "This is for educational and simulation purposes only."
"""

class Chatbot:
    """
    Handles all chat interactions.
    Supports two modes:
      1. Signal explanation  — "Why did you recommend selling Reliance?"
      2. General market Q&A — "What is RSI?", "How is my portfolio doing?"
    """

    async def respond(
        self,
        message: str,
        db: AsyncSession,
        conversation_history: list[dict] = None,
    ) -> dict:
        """
        Generate a response to a user message.

        Args:
            message:              User's question.
            db:                   DB session for context lookup.
            conversation_history: Last N turns as [{role, content}, ...].

        Returns:
            {"reply": str, "context_used": str, "signal_id": str | None}
        """
        history = conversation_history or []

        # 1. Detect intent and fetch relevant context from DB
        context, signal_id = await self._fetch_context(message, db)

        # 2. Build prompt with context injected
        user_prompt = self._build_user_prompt(message, context)

        # 3. Call LLM
        reply = await self._call_llm(user_prompt, history)

        return {
            "reply":        reply,
            "context_used": context.get("type", "general"),
            "signal_id":    signal_id,
        }

    # ------------------------------------------------------------------
    # Context fetching
    # ------------------------------------------------------------------

    async def _fetch_context(self, message: str, db: AsyncSession) -> tuple[dict, Optional[str]]:
        """
        Parse the message for signal/symbol references and fetch
        the relevant audit record. Returns (context_dict, signal_id).
        """
        msg_lower = message.lower()

        # Try to extract a symbol from the message
        symbol = await self._extract_symbol(msg_lower, db)

        if symbol:
            # Fetch most recent signal for that symbol
            asset_result = await db.execute(
                select(Asset).where(Asset.symbol == symbol)
            )
            asset = asset_result.scalar_one_or_none()

            if asset:
                sig_result = await db.execute(
                    select(Signal)
                    .where(Signal.asset_id == asset.id)
                    .order_by(desc(Signal.created_at))
                    .limit(1)
                )
                signal = sig_result.scalar_one_or_none()

                if signal:
                    return self._build_signal_context(signal, asset), str(signal.id)

        # Portfolio context for performance questions
        if any(w in msg_lower for w in ["portfolio", "wallet", "balance", "pnl", "profit", "loss"]):
            context = await self._fetch_portfolio_context(db)
            return context, None

        # No specific context — general Q&A
        return {"type": "general"}, None

    async def _extract_symbol(self, message: str, db: AsyncSession) -> Optional[str]:
        """Scan message for known asset symbols or company names."""
        result = await db.execute(select(Asset.symbol, Asset.name))
        assets = result.all()

        for symbol, name in assets:
            ticker = symbol.split(":")[-1].lower()  # e.g. NSE:RELIANCE -> reliance
            if ticker in message or name.lower().split()[0] in message:
                return symbol
        return None

    def _build_signal_context(self, signal: Signal, asset: Asset) -> dict:
        """Build a structured context dict from a signal record."""
        indicators = signal.technical_indicators or {}
        sources    = signal.sentiment_sources    or []

        return {
            "type":          "signal_explanation",
            "symbol":        asset.symbol,
            "name":          asset.name,
            "action":        signal.action.value,
            "confidence":    f"{signal.confidence:.0%}",
            "market_regime": signal.market_regime,
            "generated_at":  signal.created_at.isoformat(),

            # Model contributions
            "rl_score":          round(signal.rl_score, 4),
            "transformer_score": round(signal.transformer_score, 4),
            "sentiment_score":   round(signal.sentiment_score, 4),
            "ensemble_score":    round(signal.ensemble_score, 4),

            # Technical snapshot
            "rsi_14":        indicators.get("rsi_14"),
            "macd_line":     indicators.get("macd_line"),
            "adx":           indicators.get("adx"),
            "volume_ratio":  indicators.get("volume_ratio"),
            "atr_pct":       indicators.get("atr_pct"),

            # Sentiment headlines (up to 3)
            "news_headlines": [s.get("headline", "") for s in sources[:3]],
        }

    async def _fetch_portfolio_context(self, db: AsyncSession) -> dict:
        """Fetch current wallet and open positions summary."""
        from core.models import PaperWallet, Trade, Asset, TradeStatus
        from services.market_data.fetcher import fetch_latest_price

        wallet_result = await db.execute(select(PaperWallet).limit(1))
        wallet = wallet_result.scalar_one_or_none()
        if wallet is None:
            return {"type": "portfolio", "message": "No wallet found"}

        open_result = await db.execute(
            select(Trade, Asset)
            .join(Asset, Trade.asset_id == Asset.id)
            .where(Trade.status == TradeStatus.open)
        )
        positions = []
        for trade, asset in open_result.all():
            price = fetch_latest_price(asset.symbol) or trade.entry_price
            pnl   = (price - trade.entry_price) * trade.quantity
            positions.append({
                "symbol": asset.symbol,
                "pnl":    round(pnl, 2),
                "pnl_pct": round((price - trade.entry_price) / trade.entry_price * 100, 2),
            })

        return {
            "type":           "portfolio",
            "total_equity":   round(wallet.total_equity, 2),
            "cash_balance":   round(wallet.cash_balance, 2),
            "realized_pnl":   round(wallet.realized_pnl, 2),
            "drawdown_pct":   round(wallet.drawdown_pct * 100, 2),
            "risk_mode":      wallet.risk_mode.value,
            "open_positions": positions,
        }

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_user_prompt(self, message: str, context: dict) -> str:
        """Inject context into user message so LLM narrates real data."""
        context_type = context.get("type", "general")

        if context_type == "signal_explanation":
            return (
                f"User question: {message}\n\n"
                f"Signal data for context (use ONLY this data in your explanation):\n"
                f"{json.dumps(context, indent=2, default=str)}\n\n"
                f"Explain why the {context['action'].upper()} signal was generated for "
                f"{context['name']} ({context['symbol']}) with {context['confidence']} confidence. "
                f"Be specific about which factors (RL score, transformer forecast, sentiment, "
                f"technical indicators) drove the decision."
            )

        if context_type == "portfolio":
            return (
                f"User question: {message}\n\n"
                f"Portfolio data:\n"
                f"{json.dumps(context, indent=2, default=str)}\n\n"
                f"Answer the user's question based only on this data."
            )

        # General knowledge question
        return (
            f"User question: {message}\n\n"
            f"Answer this question about trading, technical analysis, or the platform. "
            f"Keep it educational and concise."
        )

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        user_prompt: str,
        history: list[dict],
    ) -> str:
        """Call NIM API with conversation history. Falls back to Ollama."""
        from core.config import settings
        import httpx

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-6:],    # keep last 3 turns (6 messages) for context
            {"role": "user", "content": user_prompt},
        ]

        # Try NIM first
        if settings.NVIDIA_NIM_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        f"{settings.NVIDIA_NIM_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {settings.NVIDIA_NIM_API_KEY}"},
                        json={
                            "model":       "mistralai/mistral-small-4-119b-2603",
                            "messages":    messages,
                            "max_tokens":  300,
                            "temperature": 0.2,
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"NIM chat failed: {e}")

        # Fallback to Ollama
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Flatten history into a single prompt for Ollama
                flat = "\n".join(
                    f"{m['role'].upper()}: {m['content']}" for m in messages
                )
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model":  settings.OLLAMA_MODEL,
                        "prompt": flat + "\nASSISTANT:",
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 300},
                    },
                )
                resp.raise_for_status()
                return resp.json().get("response", "").strip()
        except Exception as e:
            logger.warning(f"Ollama chat failed: {e}")

        return (
            "I couldn't generate an explanation right now — "
            "the AI service is temporarily unavailable. "
            "This is for educational and simulation purposes only."
        )


# Module-level singleton
_chatbot: Optional[Chatbot] = None

def get_chatbot() -> Chatbot:
    global _chatbot
    if _chatbot is None:
        _chatbot = Chatbot()
    return _chatbot
