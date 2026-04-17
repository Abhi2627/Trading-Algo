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
        """Reconstruct the exact same architecture used during training."""
        import torch.nn as nn

        class PriceForecasterNet(nn.Module):
            def __init__(self):
                super().__init__()
                self.input_proj = nn.Linear(n_features, d_model)
                self.pos_enc    = nn.Embedding(seq_len, d_model)
                encoder_layer   = nn.TransformerEncoderLayer(
                    d_model=d_model, nhead=n_heads,
                    dim_feedforward=d_model * 4,
                    dropout=0.1, batch_first=True,
                )
                self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
                self.head = nn.Sequential(
                    nn.Linear(d_model, 64),
                    nn.ReLU(),
                    nn.Dropout(0.1),
                    nn.Linear(64, n_outputs),
                )

            def forward(self, x):
                b, s, _ = x.shape
                import torch
                x = self.input_proj(x)
                pos = torch.arange(s, device=x.device).unsqueeze(0)
                x = x + self.pos_enc(pos)
                x = self.transformer(x)
                x = x.mean(dim=1)
                return self.head(x)

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

            # Take last SEQ_LEN entries and build numpy array
            recent = features_history[-SEQ_LEN:]
            arr = np.array(
                [[row.get(col, 0.0) for col in self._feature_cols] for row in recent],
                dtype=np.float32,
            )  # (SEQ_LEN, n_features)

            # Apply same scaler used during training
            arr_scaled = self._scaler.transform(arr)  # (SEQ_LEN, n_features)

            # Run inference
            x = torch.tensor(arr_scaled).unsqueeze(0)  # (1, SEQ_LEN, n_features)
            with torch.no_grad():
                preds = self._model(x).numpy()[0]       # (3,) → [delta_1d, delta_3d, delta_5d]

            delta_1d, delta_3d, delta_5d = float(preds[0]), float(preds[1]), float(preds[2])

            # Confidence: magnitude of 1-day prediction relative to typical moves
            # Capped at 1.0 — larger predicted moves = higher confidence
            confidence = min(abs(delta_1d) / 0.02, 1.0)  # 2% move = full confidence

            # Direction classification
            if delta_1d > 0.003:     direction = "up"
            elif delta_1d < -0.003:  direction = "down"
            else:                    direction = "sideways"

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
