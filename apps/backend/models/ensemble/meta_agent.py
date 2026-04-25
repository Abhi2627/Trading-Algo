# models/ensemble/meta_agent.py
# Meta-Agent: uses Ollama (llama3) to dynamically decide
# how much weight to give each model based on market context.
# Falls back to hardcoded regime weights if Ollama fails.
import json
import logging
import re
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3:latest"

# Hardcoded fallback weights — used when Meta-Agent fails
FALLBACK_WEIGHTS = {
    "trending": {"rl": 0.70, "transformer": 0.10, "sentiment": 0.20},
    "volatile": {"rl": 0.55, "transformer": 0.10, "sentiment": 0.35},
    "ranging":  {"rl": 0.65, "transformer": 0.10, "sentiment": 0.25},
}


class MetaAgent:
    """
    Agentic weight allocator.
    Reads market context and decides how much to trust
    each of the three models for this specific signal.

    Context inputs:
      - Market regime (trending / ranging / volatile)
      - Volatility level
      - News volume and sentiment strength
      - Each model confidence
      - RL and sentiment agreement/disagreement

    Output: weights dict {rl, transformer, sentiment} summing to 1.0
    """

    async def decide_weights(
        self,
        market_regime:       str,
        rl_confidence:       float,
        rl_action:           str,
        transformer_conf:    float,
        transformer_dir:     str,
        transformer_delta:   float,
        sentiment_score:     float,
        sentiment_magnitude: float,
        sentiment_direction: str,
        news_count:          int,
        symbol:              str,
    ) -> dict:
        """
        Ask Ollama to decide optimal weights for this signal.
        Returns validated weights dict or fallback if Ollama fails.
        """
        prompt = self._build_prompt(
            market_regime, rl_confidence, rl_action,
            transformer_conf, transformer_dir, transformer_delta,
            sentiment_score, sentiment_magnitude, sentiment_direction,
            news_count, symbol,
        )

        try:
            weights = await self._call_ollama(prompt)
            if weights and self._validate(weights):
                logger.info(
                    f"Meta-Agent {symbol}: "
                    f"rl={weights['rl']:.2f} "
                    f"tf={weights['transformer']:.2f} "
                    f"sent={weights['sentiment']:.2f}"
                )
                return {**weights, "source": "meta_agent"}
            else:
                logger.warning(f"Meta-Agent invalid response for {symbol} — fallback")
                return {**self._fallback(market_regime), "source": "fallback"}

        except Exception as e:
            logger.warning(f"Meta-Agent error for {symbol}: {e} — fallback")
            return {**self._fallback(market_regime), "source": "fallback"}

    def _build_prompt(self,
        market_regime, rl_conf, rl_action,
        tf_conf, tf_dir, tf_delta,
        sent_score, sent_mag, sent_dir,
        news_count, symbol,
    ) -> str:
        # Check if RL and sentiment agree
        rl_bullish   = rl_action == "buy"
        sent_bullish = sent_dir  == "bullish"
        agreement    = "AGREE" if rl_bullish == sent_bullish else "DISAGREE"

        return f"""You are a quantitative trading meta-agent for Indian NSE stocks.
Decide weights for three trading models for stock {symbol}.

Context:
- Market regime: {market_regime}
- RL Agent: action={rl_action}, confidence={rl_conf:.2f}
- Transformer: direction={tf_dir}, 1d_delta={tf_delta:+.4f}, confidence={tf_conf:.2f}
- Sentiment: direction={sent_dir}, score={sent_score:.2f}, magnitude={sent_mag:.2f}
- News headlines today: {news_count}
- RL vs Sentiment: {agreement}

Rules:
1. news_count>5 AND sent_mag>0.6 → sentiment weight 0.35-0.50
2. market=volatile → rl weight max 0.55, sentiment up
3. tf_conf<0.20 → transformer weight 0.05-0.10
4. tf_conf>0.40 → transformer weight up to 0.25
5. RL and sentiment AGREE → rl weight 0.60-0.70
6. RL and sentiment DISAGREE → rl max 0.50, transformer up as tiebreaker
7. All weights sum to exactly 1.0
8. Minimum any weight: 0.05

Respond with ONLY JSON, no explanation:
{{"rl": 0.XX, "transformer": 0.XX, "sentiment": 0.XX}}"""

    async def _call_ollama(self, prompt: str) -> Optional[dict]:
        """Call Ollama and extract JSON weights from response."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # low = consistent output
                    "num_predict": 60,   # only need short JSON
                },
            })
            resp.raise_for_status()
            raw = resp.json().get("response", "")

        # Extract JSON object from response
        match = re.search(r'\{[^}]+\}', raw)
        if not match:
            logger.warning(f"Meta-Agent: no JSON in response: {raw[:120]}")
            return None

        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning(f"Meta-Agent: JSON parse failed: {match.group()}")
            return None

    def _validate(self, weights: dict) -> bool:
        """Validate and normalise weights."""
        required = {"rl", "transformer", "sentiment"}
        if not required.issubset(weights.keys()):
            return False
        try:
            vals = {k: float(weights[k]) for k in required}
        except (TypeError, ValueError):
            return False
        if any(v < 0.03 or v > 0.92 for v in vals.values()):
            return False
        total = sum(vals.values())
        if abs(total - 1.0) > 0.08:
            return False
        # Normalise to exactly 1.0
        for k in required:
            weights[k] = round(float(weights[k]) / total, 4)
        return True

    def _fallback(self, market_regime: str) -> dict:
        return FALLBACK_WEIGHTS.get(market_regime, FALLBACK_WEIGHTS["ranging"])


_meta_agent: Optional[MetaAgent] = None

def get_meta_agent() -> MetaAgent:
    global _meta_agent
    if _meta_agent is None:
        _meta_agent = MetaAgent()
    return _meta_agent
