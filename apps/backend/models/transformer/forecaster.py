# models/transformer/forecaster.py
# Loads the trained Transformer and predicts forward price returns.
import pickle
import numpy as np
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent / "data" / "trained_models"
SEQ_LEN    = 60   # must match training
PRED_DAYS  = [1, 3, 5]


class PriceForecaster:
    """
    Wrapper around the trained Transformer forecaster.
    Predicts 1-day, 3-day, and 5-day forward returns.

    Usage:
        forecaster = PriceForecaster()
        if forecaster.is_ready:
            result = forecaster.predict(features_df)
    """

    def __init__(self):
        self._model        = None
        self._scaler       = None
        self._feature_cols = None
        self._meta         = None
        self.is_ready      = False
        self._load()

    def _load(self):
        try:
            import torch
            import torch.nn as nn

            model_path  = MODELS_DIR / "transformer.pth"
            scaler_path = MODELS_DIR / "transformer_scaler.pkl"

            if not model_path.exists():
                logger.warning(f"Transformer not found at {model_path}. Run Kaggle notebook 04.")
                return

            # Load checkpoint (contains weights + metadata)
            # weights_only=False required: checkpoint contains Python objects (lists, dicts)
            # This is safe here because we own the checkpoint file
            checkpoint = torch.load(str(model_path), map_location="cpu", weights_only=False)
            self._meta = {
                "n_features":   checkpoint["n_features"],
                "feature_cols": checkpoint["feature_cols"],
                "seq_len":      checkpoint["seq_len"],
                "pred_days":    checkpoint["pred_days"],
                "d_model":      checkpoint["d_model"],
                "n_heads":      checkpoint["n_heads"],
                "n_layers":     checkpoint["n_layers"],
            }
            self._feature_cols = checkpoint["feature_cols"]

            # Rebuild model architecture and load weights
            self._model = self._build_model(
                n_features=checkpoint["n_features"],
                d_model=checkpoint["d_model"],
                n_heads=checkpoint["n_heads"],
                n_layers=checkpoint["n_layers"],
                seq_len=checkpoint["seq_len"],
                n_outputs=len(checkpoint["pred_days"]),
            )
            self._model.load_state_dict(checkpoint["model_state"])
            self._model.eval()

            # Load scaler
            with open(scaler_path, "rb") as f:
                self._scaler = pickle.load(f)

            self.is_ready = True
            logger.info(
                f"Transformer loaded. "
                f"Features: {self._meta['n_features']}, "
                f"Predicts: {self._meta['pred_days']}-day returns"
            )

        except Exception as e:
            logger.exception(f"Failed to load Transformer: {e}")
            self.is_ready = False

    def _build_model(self, n_features, d_model, n_heads, n_layers, seq_len, n_outputs):
        """Reconstruct architecture matching the Kaggle notebook 04 training code."""
        import torch.nn as nn
        import math

        class PositionalEncoding(nn.Module):
            def __init__(self, d_model, max_len=5000):
                super().__init__()
                pe       = torch.zeros(max_len, d_model)
                position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
                div_term = torch.exp(
                    torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
                )
                pe[:, 0::2] = torch.sin(position * div_term)
                pe[:, 1::2] = torch.cos(position * div_term)
                self.register_buffer('pe', pe.unsqueeze(0))

            def forward(self, x):
                return x + self.pe[:, :x.size(1)]

        class PriceForecasterNet(nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding   = nn.Linear(n_features, d_model)
                self.pos_encoder = PositionalEncoding(d_model)
                encoder_layer    = nn.TransformerEncoderLayer(
                    d_model=d_model, nhead=n_heads, batch_first=True
                )
                self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
                self.fc          = nn.Linear(d_model, n_outputs)

            def forward(self, x):
                x = self.embedding(x)
                x = self.pos_encoder(x)
                x = self.transformer(x)
                return self.fc(x[:, -1, :])  # use last token, not mean pooling

        import torch
        return PriceForecasterNet()

    def predict(self, features_history: list[dict]) -> dict:
        """
        Predict forward returns from a sequence of feature dicts.

        Args:
            features_history: List of feature dicts, most recent last.
                              Must have at least SEQ_LEN entries.
                              Each dict is output of get_latest_features().

        Returns:
            {
              "delta_1d":   float  (predicted 1-day return, e.g. +0.018 = +1.8%)
              "delta_3d":   float
              "delta_5d":   float
              "confidence": float  (0–1, based on prediction magnitude)
              "direction":  "up" | "down" | "sideways"
            }
        """
        if not self.is_ready:
            return self._fallback("Transformer not loaded")

        if len(features_history) < SEQ_LEN:
            return self._fallback(f"Need {SEQ_LEN} candles, got {len(features_history)}")

        try:
            import torch

            recent = features_history[-SEQ_LEN:]
            arr = np.array(
                [[row.get(col, 0.0) for col in self._feature_cols] for row in recent],
                dtype=np.float32,
            )  # (SEQ_LEN, n_features)

            # New scaler only scales non-close columns (matches training)
            close_idx  = self._feature_cols.index('close') if 'close' in self._feature_cols else 0
            cols_to_scale = [i for i in range(len(self._feature_cols)) if i != close_idx]
            arr_scaled = arr.copy()
            arr_scaled[:, cols_to_scale] = self._scaler.transform(arr[:, cols_to_scale])

            x = torch.tensor(arr_scaled).unsqueeze(0)  # (1, SEQ_LEN, n_features)
            with torch.no_grad():
                preds = self._model(x).numpy()[0]  # (3,)

            delta_1d = float(preds[0])
            delta_3d = float(preds[1])
            delta_5d = float(preds[2])

            confidence = min(abs(delta_1d) / 0.02, 1.0)

            if delta_1d > 0.003:    direction = "up"
            elif delta_1d < -0.003: direction = "down"
            else:                   direction = "sideways"

            return {
                "delta_1d":   round(delta_1d,  6),
                "delta_3d":   round(delta_3d,  6),
                "delta_5d":   round(delta_5d,  6),
                "confidence": round(confidence, 4),
                "direction":  direction,
            }

        except Exception as e:
            logger.error(f"Transformer inference error: {e}")
            return self._fallback(str(e))

    def _fallback(self, reason: str) -> dict:
        return {
            "delta_1d":   0.0,
            "delta_3d":   0.0,
            "delta_5d":   0.0,
            "confidence": 0.0,
            "direction":  "sideways",
            "error":      reason,
        }


# Module-level singleton
_forecaster: Optional[PriceForecaster] = None

def get_forecaster() -> PriceForecaster:
    global _forecaster
    if _forecaster is None:
        _forecaster = PriceForecaster()
    return _forecaster
