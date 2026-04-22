import os
import glob
import json
import pickle
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import numpy as np
from pathlib import Path
from sklearn.preprocessing import StandardScaler
import math

# --- Setup and Environment ---
input_base = Path("/kaggle/input")
meta_files = list(input_base.rglob("meta.json"))

if not meta_files:
    raise FileNotFoundError("Could not find meta.json.")

FEATURES_DIR = meta_files[0].parent
OUTPUT_DIR   = Path("/kaggle/working")
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {DEVICE}")

with open(FEATURES_DIR / "meta.json") as f:
    META = json.load(f)

FEATURE_COLS = list(META.values())[0]["columns"]
CLOSE_IDX    = FEATURE_COLS.index("close")
N_FEATURES   = len(FEATURE_COLS)

SEQ_LEN     = 60
PRED_DAYS   = [1, 3, 5]
BATCH_SIZE  = 128
EPOCHS      = 50
LR          = 1e-4

print(f"Features: {N_FEATURES}, Close index: {CLOSE_IDX}")

# --- 1. Load Data ---
npy_files = glob.glob(str(FEATURES_DIR / "*_features.npy"))

all_arrays = []
for f in npy_files:
    arr = np.load(f).astype(np.float32)
    if len(arr) >= SEQ_LEN + max(PRED_DAYS) + 10:
        all_arrays.append(arr)
        print(f"Loaded {Path(f).stem}: {len(arr)} rows")
    else:
        print(f"SKIP {Path(f).stem}: only {len(arr)} rows")

assert len(all_arrays) > 0, "No valid data loaded."

# Concatenate all, then split 80/20
all_data_stacked  = np.concatenate(all_arrays, axis=0)
split_idx = int(len(all_data_stacked) * 0.80)
train_data = all_data_stacked[:split_idx]
val_data   = all_data_stacked[split_idx:]

print(f"\nTotal shape: {all_data_stacked.shape}")
print(f"Train shape: {train_data.shape}")
print(f"Val shape:   {val_data.shape}")

# --- 2. Scale Data ---
scaler = StandardScaler()

# Scale everything EXCEPT the close price (we need it raw for percentage returns)
cols_to_scale = [i for i in range(N_FEATURES) if i != CLOSE_IDX]
scaler.fit(train_data[:, cols_to_scale]) # Fit only on training data

with open(OUTPUT_DIR / "transformer_scaler.pkl", "wb") as f:
    pickle.dump(scaler, f)
print("Scaler saved.")

# --- 3. Dataset Class ---
class TradingDataset(Dataset):
    def __init__(self, data, seq_len, pred_days, close_idx, scaler, cols_to_scale):
        self.X = []
        self.y = []
        
        # Apply scaling to the features
        data_scaled = data.copy()
        data_scaled[:, cols_to_scale] = scaler.transform(data[:, cols_to_scale])
        
        for i in range(len(data) - seq_len - max(pred_days)):
            self.X.append(data_scaled[i : i + seq_len])
            
            # Calculate y using RAW close prices
            current_close = data[i + seq_len - 1, close_idx]
            future_closes = [data[i + seq_len - 1 + d, close_idx] for d in pred_days]
            returns = [(fc - current_close) / (abs(current_close) + 1e-9) for fc in future_closes]
            self.y.append(returns)
                
        self.X = np.array(self.X, dtype=np.float32)
        self.y = np.array(self.y, dtype=np.float32)

    def __len__(self): return len(self.X)
    def __getitem__(self, idx): return torch.tensor(self.X[idx]), torch.tensor(self.y[idx])

# --- 4. Prepare Loaders ---
train_dataset = TradingDataset(train_data, SEQ_LEN, PRED_DAYS, CLOSE_IDX, scaler, cols_to_scale)
val_dataset   = TradingDataset(val_data, SEQ_LEN, PRED_DAYS, CLOSE_IDX, scaler, cols_to_scale)

use_pinned_memory = torch.cuda.is_available()
train_dl = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, pin_memory=use_pinned_memory, num_workers=2)
val_dl   = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, pin_memory=use_pinned_memory, num_workers=2)

print(f"train_ds size: {len(train_dataset)}")
print(f"val_ds size:   {len(val_dataset)}")
print(f"train_dl batches: {len(train_dl)}")
print(f"val_dl batches:   {len(val_dl)}")

# Verify dataloaders before starting
assert len(train_dl) > 0, f"Empty train_dl! train_ds has {len(train_dataset)} samples"
assert len(val_dl)   > 0, f"Empty val_dl! val_ds has {len(val_dataset)} samples"


# --- 5. Model Definition ---
class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=5000):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0))

    def forward(self, x):
        return x + self.pe[:, :x.size(1)]

class PriceForecaster(nn.Module):
    def __init__(self, d_model=128, n_heads=8, n_layers=4):
        super().__init__()
        self.embedding = nn.Linear(N_FEATURES, d_model)
        self.pos_encoder = PositionalEncoding(d_model)
        encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=n_heads, batch_first=True)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.fc = nn.Linear(d_model, len(PRED_DAYS))

    def forward(self, x):
        x = self.embedding(x)
        x = self.pos_encoder(x)
        x = self.transformer(x)
        return self.fc(x[:, -1, :])

# --- 6. Training Loop ---
model     = PriceForecaster().to(DEVICE)
optimiser = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=EPOCHS)
criterion = nn.HuberLoss(delta=0.01)

best_val_loss    = float("inf")
patience_counter = 0
PATIENCE         = 8

print(f"\nStarting training on {DEVICE}...")

for epoch in range(1, EPOCHS + 1):
    model.train()
    train_loss = 0.0
    for X_b, y_b in train_dl:
        X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
        optimiser.zero_grad()
        
        preds = model(X_b)
        if torch.isnan(preds).any():
            continue 
            
        loss = criterion(preds, y_b)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimiser.step()
        train_loss += loss.item()
        
    train_loss /= len(train_dl)

    model.eval()
    val_loss = 0.0
    n_val_batches = 0
    with torch.no_grad():
        for X_b, y_b in val_dl:
            val_loss += criterion(model(X_b.to(DEVICE)), y_b.to(DEVICE)).item()
            n_val_batches += 1
            
    if n_val_batches == 0:
        raise RuntimeError("val_dl is empty — check val_data shape and PriceSequenceDataset")
        
    val_loss /= n_val_batches
    scheduler.step()

    print(f"Epoch {epoch:3d}/{EPOCHS}  train={train_loss:.6f}  val={val_loss:.6f}")

    if not math.isnan(val_loss) and val_loss < best_val_loss:
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
        print(f"         ✓ Best saved (val={best_val_loss:.6f})")
    else:
        patience_counter += 1
        if patience_counter >= PATIENCE:
            print(f"Early stopping at epoch {epoch}")
            break

print(f"\nDone. Best val loss: {best_val_loss:.6f}")

# --- 7. Evaluation ---
print("\nEvaluating best model...")
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
    pred_dir   = np.sign(all_preds[:, i])
    actual_dir = np.sign(all_targets[:, i])
    accuracy   = (pred_dir == actual_dir).mean()
    print(f"{d}-day directional accuracy: {accuracy:.1%}")