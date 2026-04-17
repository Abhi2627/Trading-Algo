# =============================================================================
# 04_transformer_training.py — FIXED VERSION
# No meta.json dependency — builds everything from .npy files directly
# =============================================================================

# ── Cell 1: Setup ─────────────────────────────────────────────────────────────
import numpy as np
import pandas as pd
import json
import pickle
import os
from pathlib import Path
from typing import Tuple

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler

OUTPUT_DIR = Path("/kaggle/working")
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {DEVICE}")

# Auto-detect features directory
FEATURES_DIR = None
for root, dirs, files in os.walk("/kaggle/input"):
    if any(f.endswith("_features.npy") for f in files):
        FEATURES_DIR = Path(root)
        break

assert FEATURES_DIR is not None, "Cannot find _features.npy files"
npy_files = sorted(FEATURES_DIR.glob("*_features.npy"))
print(f"Found {len(npy_files)} symbol files in {FEATURES_DIR}")

# Get feature count from sample
sample = np.load(npy_files[0]).astype(np.float32)
N_FEATURES = sample.shape[1]
print(f"Sample shape: {sample.shape}")

# Feature columns in exact order from 02_feature_engineering.py
FEATURE_COLS = [
    "close",
    "return_1d", "return_3d", "return_5d", "return_10d", "return_20d",
    "log_return_1d", "log_return_5d",
    "volatility_5d", "volatility_10d", "volatility_20d",
    "atr_14", "atr_pct",
    "price_position_52w", "price_position_20d", "gap_pct",
    "ema_9", "ema_21", "ema_50", "ema_200",
    "close_vs_ema9", "close_vs_ema21", "close_vs_ema50", "close_vs_ema200",
    "ema9_above_ema21", "ema21_above_ema50", "ema50_above_ema200",
    "macd_line", "macd_signal", "macd_histogram", "macd_above_signal",
    "adx",
    "rsi_14", "rsi_7", "rsi_overbought", "rsi_oversold",
    "stoch_k", "stoch_d", "williams_r",
    "bb_upper", "bb_mid", "bb_lower", "bb_width", "bb_position",
    "volume_ma_20", "volume_ratio", "volume_spike",
    "obv", "obv_ma_20", "obv_above_ma", "vwap_deviation",
    "is_trending", "is_high_volatility",
]

if N_FEATURES != len(FEATURE_COLS):
    print(f"WARNING: expected {len(FEATURE_COLS)} cols, got {N_FEATURES}. Using generic names.")
    FEATURE_COLS = [f"f_{i}" for i in range(N_FEATURES)]

CLOSE_IDX = FEATURE_COLS.index("close") if "close" in FEATURE_COLS else 0
SYMBOLS   = [f.stem.replace("_features", "") for f in npy_files]

print(f"N_FEATURES: {N_FEATURES}, CLOSE_IDX: {CLOSE_IDX}")
print(f"Symbols ({len(SYMBOLS)}): {SYMBOLS[:5]}...")

# Hyperparameters
SEQ_LEN    = 60
PRED_DAYS  = [1, 3, 5]
BATCH_SIZE = 128
EPOCHS     = 50
LR         = 1e-4
TRAIN_SPLIT = 0.80   # 80/20 split


# ── Cell 2: Dataset ───────────────────────────────────────────────────────────
class PriceSequenceDataset(Dataset):
    def __init__(self, features: np.ndarray, scaler=None, fit_scaler=False):
        self.features = features.astype(np.float32)
        max_horizon   = max(PRED_DAYS)

        if fit_scaler:
            self.scaler   = StandardScaler()
            self.features = self.scaler.fit_transform(self.features)
        elif scaler is not None:
            self.scaler   = scaler
            self.features = self.scaler.transform(self.features)
        else:
            self.scaler = None

        self.X, self.y = [], []
        for i in range(SEQ_LEN, len(self.features) - max_horizon):
            seq   = self.features[i - SEQ_LEN:i]
            close = self.features[i - 1, CLOSE_IDX]
            targets = []
            for d in PRED_DAYS:
                future = self.features[i + d - 1, CLOSE_IDX]
                targets.append((future - close) / (abs(close) + 1e-9))
            self.X.append(seq)
            self.y.append(targets)

        self.X = np.array(self.X, dtype=np.float32)
        self.y = np.array(self.y, dtype=np.float32)
        print(f"  Dataset: {len(self.X)} sequences")

    def __len__(self):         return len(self.X)
    def __getitem__(self, i):  return self.X[i], self.y[i]


# ── Cell 3: Model ─────────────────────────────────────────────────────────────
class PriceForecaster(nn.Module):
    def __init__(self, n_features=N_FEATURES, d_model=128, n_heads=8,
                 n_layers=4, d_ff=512, dropout=0.1, n_outputs=len(PRED_DAYS)):
        super().__init__()
        self.input_proj = nn.Linear(n_features, d_model)
        self.pos_enc    = nn.Embedding(SEQ_LEN, d_model)
        encoder_layer   = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_ff,
            dropout=dropout, batch_first=True)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.head = nn.Sequential(
            nn.Linear(d_model, 64), nn.ReLU(),
            nn.Dropout(dropout), nn.Linear(64, n_outputs))

    def forward(self, x):
        b, s, _ = x.shape
        x = self.input_proj(x)
        pos = torch.arange(s, device=x.device).unsqueeze(0)
        x = x + self.pos_enc(pos)
        x = self.transformer(x)
        x = x.mean(dim=1)
        return self.head(x)


# ── Cell 4: Load data ─────────────────────────────────────────────────────────
all_train, all_val = [], []

for f in npy_files:
    arr = np.load(f).astype(np.float32)
    split_idx = int(len(arr) * TRAIN_SPLIT)
    if split_idx < SEQ_LEN + max(PRED_DAYS) + 10:
        print(f"SKIP {f.stem}: too few rows ({len(arr)})")
        continue
    all_train.append(arr[:split_idx])
    all_val.append(arr[split_idx:])
    print(f"Loaded {f.stem}: train={split_idx} val={len(arr)-split_idx}")

train_data = np.concatenate(all_train, axis=0)
val_data   = np.concatenate(all_val,   axis=0)
print(f"\nTotal train: {train_data.shape}, val: {val_data.shape}")

train_ds = PriceSequenceDataset(train_data, fit_scaler=True)
val_ds   = PriceSequenceDataset(val_data,   scaler=train_ds.scaler)

with open(OUTPUT_DIR / "transformer_scaler.pkl", "wb") as f:
    pickle.dump(train_ds.scaler, f)
print("Scaler saved.")

train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                      num_workers=2, pin_memory=True)
val_dl   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False,
                      num_workers=2, pin_memory=True)
print(f"Train batches: {len(train_dl)}, Val batches: {len(val_dl)}")


# ── Cell 5: Train ─────────────────────────────────────────────────────────────
model     = PriceForecaster().to(DEVICE)
optimiser = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=EPOCHS)
criterion = nn.HuberLoss(delta=0.01)

best_val_loss    = float("inf")
patience_counter = 0
PATIENCE         = 8

for epoch in range(1, EPOCHS + 1):
    model.train()
    train_loss = 0.0
    for X_b, y_b in train_dl:
        X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
        optimiser.zero_grad()
        loss = criterion(model(X_b), y_b)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimiser.step()
        train_loss += loss.item()
    train_loss /= len(train_dl)

    model.eval()
    val_loss = 0.0
    with torch.no_grad():
        for X_b, y_b in val_dl:
            val_loss += criterion(model(X_b.to(DEVICE)),
                                  y_b.to(DEVICE)).item()
    val_loss /= len(val_dl)
    scheduler.step()

    print(f"Epoch {epoch:3d}/{EPOCHS}  "
          f"train={train_loss:.6f}  val={val_loss:.6f}  "
          f"lr={scheduler.get_last_lr()[0]:.2e}")

    if val_loss < best_val_loss:
        best_val_loss    = val_loss
        patience_counter = 0
        torch.save({
            "epoch":        epoch,
            "model_state":  model.state_dict(),
            "val_loss":     val_loss,
            "n_features":   N_FEATURES,
            "feature_cols": FEATURE_COLS,
            "seq_len":      SEQ_LEN,
            "pred_days":    PRED_DAYS,
            "d_model":      128,
            "n_heads":      8,
            "n_layers":     4,
        }, OUTPUT_DIR / "transformer.pth")
        print(f"          ✓ Best saved (val={best_val_loss:.6f})")
    else:
        patience_counter += 1
        if patience_counter >= PATIENCE:
            print(f"Early stopping at epoch {epoch}")
            break

print(f"\nDone. Best val loss: {best_val_loss:.6f}")


# ── Cell 6: Directional accuracy ──────────────────────────────────────────────
ckpt       = torch.load(OUTPUT_DIR / "transformer.pth", map_location=DEVICE)
best_model = PriceForecaster().to(DEVICE)
best_model.load_state_dict(ckpt["model_state"])
best_model.eval()

all_preds, all_targets = [], []
with torch.no_grad():
    for X_b, y_b in val_dl:
        all_preds.append(best_model(X_b.to(DEVICE)).cpu().numpy())
        all_targets.append(y_b.numpy())

all_preds   = np.concatenate(all_preds)
all_targets = np.concatenate(all_targets)

print("\nDirectional accuracy (>52% = has predictive edge):")
for i, d in enumerate(PRED_DAYS):
    acc = (np.sign(all_preds[:, i]) == np.sign(all_targets[:, i])).mean()
    print(f"  {d}-day: {acc:.1%}")

print("\nOutput files:")
print("  transformer.pth")
print("  transformer_scaler.pkl")
print("\nDownload and place in apps/backend/data/trained_models/")