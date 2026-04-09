# =============================================================================
# 04_transformer_training.py
# Kaggle Notebook — Price Forecasting Transformer Training
# =============================================================================
# HOW TO USE:
# 1. Create a new Kaggle notebook
# 2. Add dataset: abhay1226/trading-platform-features
# 3. Set accelerator: GPU T4 x2 (or P100)
# 4. Enable internet: ON
# 5. Paste this entire file, run all — takes 20–40 min
# 6. Download output: transformer.pth + transformer_scaler.pkl
# 7. Place at: apps/backend/data/trained_models/
# =============================================================================

# ── Cell 1: Imports ───────────────────────────────────────────────────────────
import numpy as np
import pandas as pd
import json
import pickle
from pathlib import Path
from typing import Tuple

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler

FEATURES_DIR = Path("/kaggle/input/trading-platform-features/features")
OUTPUT_DIR   = Path("/kaggle/working")

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {DEVICE}")

# Load metadata
with open(FEATURES_DIR / "meta.json") as f:
    META = json.load(f)

FEATURE_COLS = list(META.values())[0]["columns"]
CLOSE_IDX    = FEATURE_COLS.index("close")
N_FEATURES   = len(FEATURE_COLS)

print(f"Features: {N_FEATURES}, Close index: {CLOSE_IDX}")

# Hyperparameters
SEQ_LEN    = 60    # look back 60 trading days (~3 months)
PRED_DAYS  = [1, 3, 5]  # predict 1-day, 3-day, 5-day forward returns
BATCH_SIZE = 128
EPOCHS     = 50
LR         = 1e-4
TRAIN_SPLIT = 1260


# ── Cell 2: Dataset ──────────────────────────────────────────────────────────
class PriceSequenceDataset(Dataset):
    """
    Sliding window dataset.
    X: sequence of SEQ_LEN feature vectors
    y: forward returns for PRED_DAYS horizons
       y[0] = 1-day forward return
       y[1] = 3-day forward return
       y[2] = 5-day forward return
    """
    def __init__(self, features: np.ndarray, scaler: StandardScaler = None, fit_scaler: bool = False):
        self.features = features.astype(np.float32)
        max_horizon   = max(PRED_DAYS)

        # Fit or apply scaler
        if fit_scaler:
            self.scaler = StandardScaler()
            self.features = self.scaler.fit_transform(self.features)
        elif scaler is not None:
            self.scaler = scaler
            self.features = self.scaler.transform(self.features)
        else:
            self.scaler = None

        # Build sequences
        self.X, self.y = [], []
        for i in range(SEQ_LEN, len(self.features) - max_horizon):
            seq    = self.features[i - SEQ_LEN:i]          # (SEQ_LEN, N_FEATURES)
            close  = self.features[i - 1, CLOSE_IDX]       # current close (scaled)

            # Forward returns at each horizon
            targets = []
            for d in PRED_DAYS:
                future_close = self.features[i + d - 1, CLOSE_IDX]
                ret = (future_close - close) / (abs(close) + 1e-9)
                targets.append(ret)

            self.X.append(seq)
            self.y.append(targets)

        self.X = np.array(self.X, dtype=np.float32)  # (n, SEQ_LEN, N_FEATURES)
        self.y = np.array(self.y, dtype=np.float32)  # (n, len(PRED_DAYS))

    def __len__(self):  return len(self.X)
    def __getitem__(self, i): return self.X[i], self.y[i]


# ── Cell 3: Model architecture ───────────────────────────────────────────────
class PriceForecaster(nn.Module):
    """
    Transformer encoder for price sequence forecasting.

    Architecture:
      Input projection: N_FEATURES → d_model
      Positional encoding (learnable)
      4x Transformer encoder layers
      Global average pooling
      Regression head: d_model → len(PRED_DAYS)
    """
    def __init__(
        self,
        n_features: int = N_FEATURES,
        d_model: int = 128,
        n_heads: int = 8,
        n_layers: int = 4,
        d_ff: int = 512,
        dropout: float = 0.1,
        n_outputs: int = len(PRED_DAYS),
    ):
        super().__init__()
        self.d_model = d_model

        # Project input features to model dimension
        self.input_proj = nn.Linear(n_features, d_model)

        # Learnable positional encoding
        self.pos_enc = nn.Embedding(SEQ_LEN, d_model)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_ff,
            dropout=dropout,
            batch_first=True,   # (batch, seq, features)
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        # Output head
        self.head = nn.Sequential(
            nn.Linear(d_model, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, n_outputs),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, n_features)
        batch_size, seq_len, _ = x.shape

        # Project to d_model
        x = self.input_proj(x)  # (batch, seq_len, d_model)

        # Add positional encoding
        positions = torch.arange(seq_len, device=x.device).unsqueeze(0)  # (1, seq_len)
        x = x + self.pos_enc(positions)  # broadcast over batch

        # Transformer encoder
        x = self.transformer(x)   # (batch, seq_len, d_model)

        # Global average pooling over sequence dimension
        x = x.mean(dim=1)         # (batch, d_model)

        # Predict forward returns
        return self.head(x)       # (batch, n_outputs)


# ── Cell 4: Load and prepare data ────────────────────────────────────────────
all_train, all_val = [], []

for symbol in META.keys():
    path = FEATURES_DIR / f"{symbol}_features.npy"
    if not path.exists():
        continue
    arr = np.load(path).astype(np.float32)
    all_train.append(arr[:TRAIN_SPLIT])
    all_val.append(arr[TRAIN_SPLIT:])

# Concatenate all symbols for training (more data = better generalisation)
train_data = np.concatenate(all_train, axis=0)
val_data   = np.concatenate(all_val,   axis=0)

print(f"Train: {train_data.shape}, Val: {val_data.shape}")

# Create datasets (fit scaler on train only)
train_ds = PriceSequenceDataset(train_data, fit_scaler=True)
val_ds   = PriceSequenceDataset(val_data,   scaler=train_ds.scaler, fit_scaler=False)

# Save scaler — required for inference
with open(OUTPUT_DIR / "transformer_scaler.pkl", "wb") as f:
    pickle.dump(train_ds.scaler, f)

train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  num_workers=2, pin_memory=True)
val_dl   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=2, pin_memory=True)

print(f"Train batches: {len(train_dl)}, Val batches: {len(val_dl)}")


# ── Cell 5: Train ───────────────────────────────────────────────────────────────
model     = PriceForecaster().to(DEVICE)
optimiser = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=EPOCHS)
# Huber loss — robust to return spikes (outliers in financial data)
criterion = nn.HuberLoss(delta=0.01)

best_val_loss = float("inf")
patience_counter = 0
PATIENCE = 8

for epoch in range(1, EPOCHS + 1):
    # —— Train ———————————————————————————————————————
    model.train()
    train_loss = 0.0
    for X_batch, y_batch in train_dl:
        X_batch = X_batch.to(DEVICE)
        y_batch = y_batch.to(DEVICE)
        optimiser.zero_grad()
        preds = model(X_batch)
        loss  = criterion(preds, y_batch)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimiser.step()
        train_loss += loss.item()
    train_loss /= len(train_dl)

    # —— Validate ——————————————————————————————————————
    model.eval()
    val_loss = 0.0
    with torch.no_grad():
        for X_batch, y_batch in val_dl:
            X_batch = X_batch.to(DEVICE)
            y_batch = y_batch.to(DEVICE)
            preds    = model(X_batch)
            val_loss += criterion(preds, y_batch).item()
    val_loss /= len(val_dl)
    scheduler.step()

    print(f"Epoch {epoch:3d}/{EPOCHS}  train={train_loss:.6f}  val={val_loss:.6f}  lr={scheduler.get_last_lr()[0]:.2e}")

    # Save best model
    if val_loss < best_val_loss:
        best_val_loss = val_loss
        patience_counter = 0
        torch.save({
            "epoch":       epoch,
            "model_state": model.state_dict(),
            "val_loss":    val_loss,
            "n_features":  N_FEATURES,
            "feature_cols": FEATURE_COLS,
            "seq_len":     SEQ_LEN,
            "pred_days":   PRED_DAYS,
            "d_model":     128,
            "n_heads":     8,
            "n_layers":    4,
        }, OUTPUT_DIR / "transformer.pth")
        print(f"          ✓ New best saved (val_loss={best_val_loss:.6f})")
    else:
        patience_counter += 1
        if patience_counter >= PATIENCE:
            print(f"Early stopping at epoch {epoch}")
            break

print(f"\nTraining complete. Best val loss: {best_val_loss:.6f}")


# ── Cell 6: Directional accuracy test ───────────────────────────────────────
# Load best model and test directional accuracy on validation set
checkpoint = torch.load(OUTPUT_DIR / "transformer.pth", map_location=DEVICE)
best_model  = PriceForecaster().to(DEVICE)
best_model.load_state_dict(checkpoint["model_state"])
best_model.eval()

all_preds, all_targets = [], []
with torch.no_grad():
    for X_batch, y_batch in val_dl:
        preds = best_model(X_batch.to(DEVICE)).cpu().numpy()
        all_preds.append(preds)
        all_targets.append(y_batch.numpy())

all_preds   = np.concatenate(all_preds,   axis=0)
all_targets = np.concatenate(all_targets, axis=0)

for i, d in enumerate(PRED_DAYS):
    # Directional accuracy: did we predict the right sign?
    pred_dir   = np.sign(all_preds[:, i])
    actual_dir = np.sign(all_targets[:, i])
    accuracy   = (pred_dir == actual_dir).mean()
    print(f"{d}-day directional accuracy: {accuracy:.1%}")

# >52% directional accuracy means the model has predictive edge
# Random baseline = 50%
print("\nFiles saved:")
print(f"  transformer.pth          (model weights + metadata)")
print(f"  transformer_scaler.pkl   (StandardScaler for inference)")
print("\nDownload both files and place in apps/backend/data/trained_models/")
