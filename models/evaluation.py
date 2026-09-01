"""Shared evaluation utilities for the yield regression models (Phase 8-9).

Concept: a temporal split (train on earlier years, test on later years),
not a random split, because the real business question is "predict next
season's yield" - a random split would let the model "see the future"
during training (e.g. train on Region X/2010 while testing on Region
X/2008), which no real deployment could ever do. This also means no
row-level shuffling can leak information across the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


@dataclass
class RegressionMetrics:
    mae: float
    rmse: float
    r2: float
    n: int

    def __str__(self) -> str:
        return f"MAE={self.mae:,.1f}  RMSE={self.rmse:,.1f}  R2={self.r2:.4f}  (n={self.n})"


def temporal_split(df: pd.DataFrame, cutoff_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train = strictly before cutoff_year, test = cutoff_year onward."""
    train = df[df["year"] < cutoff_year].copy()
    test = df[df["year"] >= cutoff_year].copy()
    return train, test


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> RegressionMetrics:
    return RegressionMetrics(
        mae=mean_absolute_error(y_true, y_pred),
        rmse=float(np.sqrt(mean_squared_error(y_true, y_pred))),
        r2=r2_score(y_true, y_pred),
        n=len(y_true),
    )
