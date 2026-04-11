# models/sentiment/sentiment_service.py
# Calls NVIDIA NIM API for sentiment analysis with Ollama as fallback.
# Never stores API keys here — always reads from core.config.
import json
import logging
import httpx
from typing import Optional
from core.config import settings

logger = logging.getLogger(__name__)

SENTIMENT_SYSTEM_PROMPT = """
You are a financial sentiment analyser.
Analyse the provided news headlines about a stock and return ONLY valid JSON.
No preamble, no explanation, no markdown. Raw JSON only.

JSON format:
{
  "score": <float from -1.0 (very bearish) to +1.0 (very bullish)>,
  "magnitude": <float 0.0 to 1.0, how strong/certain the sentiment is>,
  "direction": "bullish" | "bearish" | "neutral",
  "key_factors": [<list of 2-3 specific reasons driving sentiment>],
  "time_horizon": "immediate" | "short_term" | "long_term"
}
"""


class SentimentService:
    """
    Runs sentiment analysis on news headlines.
    Primary: NVIDIA NIM API (mistral-small, free tier)
    Fallback: Local Ollama (llama3.2:3b)

    Usage:
        svc = SentimentService()
        result = await svc.analyse(["headline 1", "headline 2"], symbol="NSE:RELIANCE")
    """

    async def analyse(
        self,
        headlines: list[str],
        symbol: str = "",
    ) -> dict:
        """
        Score sentiment from a list of headlines.

        Returns:
            {
              "score":        float (-1 to +1)
              "magnitude":    float (0 to 1)
              "direction":    "bullish" | "bearish" | "neutral"
              "key_factors":  list[str]
              "time_horizon": str
              "source":       "nim" | "ollama" | "fallback"
            }
        """
        if not headlines:
            return self._neutral("no headlines provided")

        prompt = self._build_prompt(headlines, symbol)

        # Try NIM first
        if settings.NVIDIA_NIM_API_KEY:
            result = await self._call_nim(prompt)
            if result:
                result["source"] = "nim"
                return result

        # Fallback to Ollama
        result = await self._call_ollama(prompt)
        if result:
            result["source"] = "ollama"
            return result

        return self._neutral("all providers failed")

    def _build_prompt(self, headlines: list[str], symbol: str) -> str:
        headlines_text = "\n".join(f"- {h}" for h in headlines[:10])  # cap at 10
        return (
            f"Analyse the market sentiment for {symbol or 'this stock'} "
            f"based on these recent headlines:\n\n{headlines_text}\n\n"
            f"Return only the JSON object."
        )

    async def _call_nim(self, prompt: str) -> Optional[dict]:
        """Call NVIDIA NIM API (OpenAI-compatible endpoint)."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{settings.NVIDIA_NIM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.NVIDIA_NIM_API_KEY}",
                        "Content-Type":  "application/json",
                    },
                    json={
                        "model": "mistralai/mistral-small-4-119b-2603",
                        "messages": [
                            {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
                            {"role": "user",   "content": prompt},
                        ],
                        "max_tokens":  300,
                        "temperature": 0.1,  # low temp for consistent JSON
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return self._parse_json(content)

        except Exception as e:
            logger.warning(f"NIM API call failed: {e}")
            return None

    async def _call_ollama(self, prompt: str) -> Optional[dict]:
        """Call local Ollama as fallback."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model":  settings.OLLAMA_MODEL,
                        "prompt": f"{SENTIMENT_SYSTEM_PROMPT}\n\nUser: {prompt}\n\nAssistant:",
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1},
                    },
                )
                response.raise_for_status()
                content = response.json().get("response", "")
                return self._parse_json(content)

        except Exception as e:
            logger.warning(f"Ollama call failed: {e}")
            return None

    def _parse_json(self, content: str) -> Optional[dict]:
        """Parse and validate LLM JSON output."""
        try:
            # Strip markdown fences if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            data = json.loads(content.strip())

            # Validate required fields
            score     = float(data.get("score", 0.0))
            magnitude = float(data.get("magnitude", 0.5))

            # Clamp to valid ranges
            score     = max(-1.0, min(1.0, score))
            magnitude = max(0.0,  min(1.0, magnitude))

            return {
                "score":        round(score, 4),
                "magnitude":    round(magnitude, 4),
                "direction":    data.get("direction",    "neutral"),
                "key_factors":  data.get("key_factors",  []),
                "time_horizon": data.get("time_horizon", "short_term"),
            }

        except Exception as e:
            logger.warning(f"Failed to parse sentiment JSON: {e}. Content: {content[:200]}")
            return None

    def _neutral(self, reason: str = "") -> dict:
        return {
            "score":        0.0,
            "magnitude":    0.0,
            "direction":    "neutral",
            "key_factors":  [],
            "time_horizon": "short_term",
            "source":       "fallback",
            "reason":       reason,
        }


# Module-level singleton
_service: Optional[SentimentService] = None

def get_sentiment_service() -> SentimentService:
    global _service
    if _service is None:
        _service = SentimentService()
    return _service
