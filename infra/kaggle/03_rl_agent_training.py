# =============================================================================
# 03_rl_agent_training.py
# Kaggle Notebook — PPO Reinforcement Learning Agent Training
# =============================================================================
# HOW TO USE:
# 1. Create a new Kaggle notebook
# 2. Add dataset: abhay1226/trading-platform-features
# 3. Set accelerator: GPU T4 x2 (or P100)
# 4. Enable internet: ON
# 5. Paste this entire file, run all — takes 30–60 min
# 6. Download output: rl_agent.zip
# 7. Place at: apps/backend/data/trained_models/rl_agent.zip
# =============================================================================

# ── Cell 1: Install ─────────────────────────────────────────────────────────────
import subprocess
subprocess.run(["pip", "install", "stable-baselines3[extra]", "gymnasium", "-q"], check=True)

# ── Cell 2: Imports ───────────────────────────────────────────────────────────
import numpy as np
import pandas as pd
import json
import os
from pathlib import Path
from typing import Optional

import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnNoModelImprovement
from stable_baselines3.common.monitor import Monitor

FEATURES_DIR = Path("/kaggle/input/trading-platform-features/features")
OUTPUT_DIR   = Path("/kaggle/working")

# Load metadata to get feature columns
with open(FEATURES_DIR / "meta.json") as f:
    META = json.load(f)

FEATURE_COLS = list(META.values())[0]["columns"]
N_FEATURES   = len(FEATURE_COLS)
CLOSE_IDX    = FEATURE_COLS.index("close")  # index of close price in feature vector

print(f"Feature columns: {N_FEATURES}")
print(f"Close price index: {CLOSE_IDX}")

# ── Cell 3: Trading Environment ────────────────────────────────────────────
ACTION_HOLD = 0
ACTION_BUY  = 1
ACTION_SELL = 2

class TradingEnv(gym.Env):
    """
    Paper trading environment for RL training.

    State:  80+ technical features + portfolio state (5 values)
    Action: 0=HOLD, 1=BUY, 2=SELL
    Reward: Risk-adjusted return (Sharpe-based), penalised for overtrading
            and large drawdowns.
    """
    metadata = {"render_modes": []}

    def __init__(
        self,
        features: np.ndarray,   # shape: (n_steps, n_features)
        initial_capital: float = 10_000.0,
        transaction_cost: float = 0.001,   # 0.1% per trade (brokerage simulation)
        max_position_pct: float = 0.10,    # max 10% of capital per position
        window_size: int = 1,              # how many steps the agent sees at once
    ):
        super().__init__()
        self.features         = features
        self.initial_capital  = initial_capital
        self.transaction_cost = transaction_cost
        self.max_position_pct = max_position_pct
        self.window_size      = window_size
        self.n_steps          = len(features)

        # Observation: features + [cash_ratio, position, unrealised_pnl_pct,
        #                           days_held_norm, drawdown_pct]
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(N_FEATURES + 5,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(3)  # HOLD / BUY / SELL

        self._reset_state()

    def _reset_state(self):
        self.step_idx        = 0
        self.cash            = self.initial_capital
        self.position        = 0.0   # number of shares held
        self.entry_price     = 0.0
        self.days_held       = 0
        self.peak_equity     = self.initial_capital
        self.portfolio_value = self.initial_capital
        self.prev_value      = self.initial_capital
        self.returns_log     = []

    def _current_price(self) -> float:
        return float(self.features[self.step_idx, CLOSE_IDX])

    def _portfolio_value(self) -> float:
        price = self._current_price()
        return self.cash + self.position * price

    def _get_obs(self) -> np.ndarray:
        feat = self.features[self.step_idx].copy()
        total = self._portfolio_value()
        price = self._current_price()
        unrealised = ((price - self.entry_price) / (self.entry_price + 1e-9)
                      if self.position > 0 else 0.0)
        drawdown = max(0.0, (self.peak_equity - total) / (self.peak_equity + 1e-9))
        portfolio_state = np.array([
            self.cash / (self.initial_capital + 1e-9),  # cash ratio
            1.0 if self.position > 0 else 0.0,          # in position flag
            unrealised,                                  # unrealised P&L %
            min(self.days_held / 30.0, 1.0),             # days held (normalised)
            drawdown,                                    # current drawdown
        ], dtype=np.float32)
        return np.concatenate([feat, portfolio_state]).astype(np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._reset_state()
        return self._get_obs(), {}

    def step(self, action: int):
        price    = self._current_price()
        total    = self._portfolio_value()
        reward   = 0.0
        done     = False
        info     = {}

        # ——— Execute action ————————————————————————————————————————
        if action == ACTION_BUY and self.position == 0:
            # Buy: invest max_position_pct of current equity
            invest     = total * self.max_position_pct
            cost       = invest * self.transaction_cost
            shares     = (invest - cost) / (price + 1e-9)
            self.cash -= invest
            self.position   = shares
            self.entry_price = price
            self.days_held   = 0
            reward -= cost / (self.initial_capital + 1e-9)  # transaction cost penalty

        elif action == ACTION_SELL and self.position > 0:
            # Sell: close position
            proceeds = self.position * price
            cost     = proceeds * self.transaction_cost
            self.cash    += proceeds - cost
            pnl_pct       = (price - self.entry_price) / (self.entry_price + 1e-9)
            reward        += pnl_pct * 0.5   # partial reward on close
            self.position    = 0.0
            self.entry_price = 0.0
            self.days_held   = 0
            reward -= cost / (self.initial_capital + 1e-9)

        elif action == ACTION_HOLD and self.position > 0:
            self.days_held += 1

        # ——— Portfolio update ———————————————————————————————————————
        new_total = self._portfolio_value()
        step_return = (new_total - self.prev_value) / (self.prev_value + 1e-9)
        self.returns_log.append(step_return)
        self.prev_value = new_total

        # Update peak equity for drawdown calculation
        if new_total > self.peak_equity:
            self.peak_equity = new_total

        # ——— Reward shaping ———————————————————————————————————————
        # Sharpe-based reward: penalise volatility of returns
        if len(self.returns_log) >= 20:
            r_arr  = np.array(self.returns_log[-20:])
            sharpe = r_arr.mean() / (r_arr.std() + 1e-9) * np.sqrt(252)
            reward += sharpe * 0.01

        # Drawdown penalty
        drawdown = (self.peak_equity - new_total) / (self.peak_equity + 1e-9)
        if drawdown > 0.10:
            reward -= drawdown * 0.5

        # Holding too long penalty (dead money)
        if self.days_held > 20:
            reward -= 0.001 * (self.days_held - 20)

        # ——— Advance step —————————————————————————————————————————
        self.step_idx += 1
        if self.step_idx >= self.n_steps - 1:
            done = True
            # Force sell any open position at end of episode
            if self.position > 0:
                self.cash += self.position * price
                self.position = 0.0

        info["portfolio_value"] = new_total
        info["drawdown"]        = drawdown

        truncated = False
        return self._get_obs(), reward, done, truncated, info

    def render(self):
        pass


# ── Cell 4: Load data and create train/val split ────────────────────────────
def load_features(symbol: str) -> Optional[np.ndarray]:
    path = FEATURES_DIR / f"{symbol}_features.npy"
    if not path.exists():
        return None
    return np.load(path).astype(np.float32)


# Load all symbols, split train (2018–2022) / val (2023–2024)
# We use row counts since the .npy files don’t have dates
# 1726 rows total per equity symbol — roughly 252 rows/year
# 2018–2022 = 5 years ≈ 1260 rows | 2023–2024 ≈ 466 rows
TRAIN_SPLIT = 1260

train_arrays, val_arrays = [], []

for symbol in META.keys():
    arr = load_features(symbol)
    if arr is None:
        print(f"Missing: {symbol}")
        continue
    train_arrays.append(arr[:TRAIN_SPLIT])
    val_arrays.append(arr[TRAIN_SPLIT:])
    print(f"Loaded {symbol}: train={len(arr[:TRAIN_SPLIT])} val={len(arr[TRAIN_SPLIT:])}")

print(f"\nTotal train arrays: {len(train_arrays)}")
print(f"Total val arrays:   {len(val_arrays)}")


# ── Cell 5: Create vectorised environments ──────────────────────────────────
def make_env(features_array):
    def _init():
        env = TradingEnv(features_array)
        env = Monitor(env)
        return env
    return _init

# Use first 8 symbols for training envs (multi-env speeds up PPO)
train_envs = DummyVecEnv([make_env(arr) for arr in train_arrays[:8]])
train_envs = VecNormalize(train_envs, norm_obs=True, norm_reward=True)

# Single val env on a held-out symbol
val_env = DummyVecEnv([make_env(val_arrays[0])])
val_env = VecNormalize(val_env, norm_obs=True, norm_reward=False, training=False)

print("Environments created.")
print(f"Obs space: {train_envs.observation_space}")
print(f"Action space: {train_envs.action_space}")


# ── Cell 6: Define and train PPO model ────────────────────────────────────
model = PPO(
    policy="MlpPolicy",
    env=train_envs,
    learning_rate=3e-4,
    n_steps=2048,          # steps per env before update
    batch_size=256,
    n_epochs=10,
    gamma=0.99,            # discount factor
    gae_lambda=0.95,       # GAE lambda
    clip_range=0.2,
    ent_coef=0.01,         # entropy bonus (encourages exploration)
    vf_coef=0.5,
    max_grad_norm=0.5,
    policy_kwargs=dict(
        net_arch=[256, 256, 128],  # 3-layer MLP policy network
    ),
    verbose=1,
    device="auto",         # uses GPU automatically if available
)

# Early stopping if val reward stops improving
stop_callback = StopTrainingOnNoModelImprovement(
    max_no_improvement_evals=5,
    min_evals=10,
    verbose=1,
)
eval_callback = EvalCallback(
    val_env,
    best_model_save_path=str(OUTPUT_DIR / "best_model"),
    log_path=str(OUTPUT_DIR / "eval_logs"),
    eval_freq=10_000,
    n_eval_episodes=3,
    callback_after_eval=stop_callback,
    verbose=1,
)

print("Starting PPO training...")
print(f"Total timesteps: 1,000,000")
print(f"Estimated time: 30–60 min on GPU")

model.learn(
    total_timesteps=1_000_000,
    callback=eval_callback,
    progress_bar=True,
)

print("Training complete.")


# ── Cell 7: Save model and normalisation stats ──────────────────────────────
# Save the final model
model.save(str(OUTPUT_DIR / "rl_agent"))

# Save VecNormalize stats — CRITICAL: must use same stats during inference
train_envs.save(str(OUTPUT_DIR / "vec_normalize.pkl"))

# Save feature column names — inference must use exact same features in same order
with open(OUTPUT_DIR / "feature_cols.json", "w") as f:
    json.dump(FEATURE_COLS, f)

print("Saved:")
print(f"  {OUTPUT_DIR}/rl_agent.zip")
print(f"  {OUTPUT_DIR}/vec_normalize.pkl")
print(f"  {OUTPUT_DIR}/feature_cols.json")


# ── Cell 8: Quick validation on held-out data ─────────────────────────────
from stable_baselines3 import PPO as PPO_load

# Test on a completely unseen symbol (last in list)
unseen_symbol = list(META.keys())[-1]
unseen_arr    = load_features(unseen_symbol)
unseen_env    = DummyVecEnv([make_env(unseen_arr[TRAIN_SPLIT:])])

obs = unseen_env.reset()
total_reward  = 0.0
portfolio_log = []
action_counts = {0: 0, 1: 0, 2: 0}

for _ in range(len(unseen_arr[TRAIN_SPLIT:]) - 1):
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, done, info = unseen_env.step(action)
    total_reward += reward[0]
    action_counts[int(action[0])] += 1
    if info[0]:
        portfolio_log.append(info[0].get("portfolio_value", 0))
    if done[0]:
        break

final_value  = portfolio_log[-1] if portfolio_log else 10_000
return_pct   = (final_value - 10_000) / 10_000 * 100

print(f"\nValidation on {unseen_symbol} (unseen during training):")
print(f"  Final portfolio value: ₹{final_value:,.2f}")
print(f"  Total return:          {return_pct:+.1f}%")
print(f"  Action distribution:   HOLD={action_counts[0]} BUY={action_counts[1]} SELL={action_counts[2]}")
print(f"  Total reward:          {total_reward:.4f}")

if return_pct > 0:
    print("\n✅ Model shows positive returns on unseen data. Safe to use.")
else:
    print("\n⚠️  Model shows negative returns. Consider more training timesteps or reward tuning.")
