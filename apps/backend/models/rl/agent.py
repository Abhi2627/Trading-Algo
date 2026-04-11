# models/rl/agent.py
# Loads the trained PPO agent and runs inference.
# Never import training libraries here — inference only.
import json
import pickle
import numpy as np
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent / "data" / "trained_models"

# Action constants — must match training environment exactly
ACTION_HOLD = 0
ACTION_BUY  = 1
ACTION_SELL = 2

ACTION_LABELS = {ACTION_HOLD: "hold", ACTION_BUY: "buy", ACTION_SELL: "sell"}


class RLAgent:
    """
    Wrapper around the trained PPO agent.
    Loads model once at startup, runs fast inference per request.

    Usage:
        agent = RLAgent()
        if agent.is_ready:
            result = agent.predict(features, portfolio_state)
    """

    def __init__(self):
        self._model        = None
        self._vec_norm     = None
        self._feature_cols = None
        self.is_ready      = False
        self._load()

    def _load(self):
        """Load model, normaliser, and feature column list from disk."""
        try:
            from stable_baselines3 import PPO
            from stable_baselines3.common.vec_env import VecNormalize, DummyVecEnv
            import gymnasium as gym

            agent_path   = MODELS_DIR / "rl_agent.zip"
            norm_path    = MODELS_DIR / "vec_normalize.pkl"
            cols_path    = MODELS_DIR / "feature_cols.json"

            if not agent_path.exists():
                logger.warning(f"RL agent not found at {agent_path}. Run Kaggle notebook 03.")
                return

            # Load feature column list
            with open(cols_path) as f:
                self._feature_cols = json.load(f)

            # Load VecNormalize stats (used to normalise observations at inference)
            with open(norm_path, "rb") as f:
                self._vec_norm = pickle.load(f)

            # Load PPO model (custom_objects silences version warnings)
            self._model = PPO.load(
                str(agent_path),
                custom_objects={"learning_rate": 0.0, "lr_schedule": lambda _: 0.0},
            )

            self.is_ready = True
            logger.info(f"RL agent loaded. Features: {len(self._feature_cols)}")

        except Exception as e:
            logger.error(f"Failed to load RL agent: {e}")
            self.is_ready = False

    def predict(
        self,
        features: dict,
        portfolio_state: Optional[dict] = None,
    ) -> dict:
        """
        Run one inference step.

        Args:
            features:        Output of get_latest_features() — flat dict of feature values.
            portfolio_state: Optional portfolio context.
                             Keys: cash_ratio, in_position, unrealised_pnl,
                                   days_held_norm, drawdown_pct

        Returns:
            {
              "action":      "buy" | "sell" | "hold",
              "action_id":   0 | 1 | 2,
              "confidence":  float (0–1, based on action probability),
              "q_values":    [hold_q, buy_q, sell_q],
            }
        """
        if not self.is_ready:
            return self._fallback("RL agent not loaded")

        try:
            # Build feature vector in exact training order
            feat_vec = np.array(
                [features.get(col, 0.0) for col in self._feature_cols],
                dtype=np.float32,
            )

            # Append portfolio state (5 values, same as training env)
            if portfolio_state is None:
                portfolio_state = {}
            port_vec = np.array([
                portfolio_state.get("cash_ratio",      1.0),
                portfolio_state.get("in_position",     0.0),
                portfolio_state.get("unrealised_pnl",  0.0),
                portfolio_state.get("days_held_norm",  0.0),
                portfolio_state.get("drawdown_pct",    0.0),
            ], dtype=np.float32)

            obs = np.concatenate([feat_vec, port_vec]).reshape(1, -1)

            # Apply VecNormalize stats (must match training)
            obs_norm = self._vec_norm.normalize_obs(obs)

            # Get action and log probabilities
            action, _ = self._model.predict(obs_norm, deterministic=True)
            action_id  = int(action[0])

            # Get action probabilities for confidence score
            obs_tensor = self._model.policy.obs_to_tensor(obs_norm)[0]
            dist       = self._model.policy.get_distribution(obs_tensor)
            probs      = dist.distribution.probs.detach().cpu().numpy()[0]

            return {
                "action":    ACTION_LABELS[action_id],
                "action_id": action_id,
                "confidence": float(probs[action_id]),
                "q_values":  probs.tolist(),
            }

        except Exception as e:
            logger.error(f"RL inference error: {e}")
            return self._fallback(str(e))

    def _fallback(self, reason: str) -> dict:
        return {
            "action":     "hold",
            "action_id":  ACTION_HOLD,
            "confidence": 0.0,
            "q_values":   [1.0, 0.0, 0.0],
            "error":      reason,
        }


# Module-level singleton — loaded once when backend starts
_agent: Optional[RLAgent] = None

def get_rl_agent() -> RLAgent:
    global _agent
    if _agent is None:
        _agent = RLAgent()
    return _agent
