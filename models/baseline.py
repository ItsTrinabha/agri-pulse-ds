"""Phase 8 - ML fundamentals: the first baseline yield model.

Concept: a baseline is the simplest defensible prediction strategy - here,
"predict this (region, crop)'s historical average yield, computed only
from training years." Any real model built in Phase 9 has to beat this to
be worth the added complexity; if it can't, the complexity isn't earning
its keep. This IS the ML workflow end-to-end (features -> train -> predict
-> evaluate), just with the simplest possible "model."

Label: yield_hg_ha. "Features" here are just (region, crop) used as a
lookup key, not numeric model inputs - Phase 9 adds real features
(rainfall, temperature, pesticide use, engineered variables).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from models.evaluation import evaluate, temporal_split

CUTOFF_YEAR = 2005


class HistoricalAverageBaseline:
    """predict(region, crop) = mean training yield for that (region, crop);
    falls back to the crop's overall training mean if this (region, crop)
    pair has no training history (cold start) - and to the global training
    mean if even the crop is unseen."""

    def fit(self, train: pd.DataFrame) -> "HistoricalAverageBaseline":
        self.region_crop_mean_ = train.groupby(["area", "crop"])["yield_hg_ha"].mean().to_dict()
        self.crop_mean_ = train.groupby("crop")["yield_hg_ha"].mean().to_dict()
        self.global_mean_ = train["yield_hg_ha"].mean()
        return self

    def predict(self, test: pd.DataFrame) -> np.ndarray:
        preds = []
        for area, crop in zip(test["area"], test["crop"]):
            if (area, crop) in self.region_crop_mean_:
                preds.append(self.region_crop_mean_[(area, crop)])
            elif crop in self.crop_mean_:
                preds.append(self.crop_mean_[crop])
            else:
                preds.append(self.global_mean_)
        return np.array(preds)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")

    train, test = temporal_split(df, CUTOFF_YEAR)
    print(f"Train: {len(train)} rows (years < {CUTOFF_YEAR}), Test: {len(test)} rows (years >= {CUTOFF_YEAR})")

    model = HistoricalAverageBaseline().fit(train)
    preds = model.predict(test)

    metrics = evaluate(test["yield_hg_ha"].to_numpy(), preds)
    print(f"\nHistorical-average baseline: {metrics}")

    cold_start = sum(
        1 for a, c in zip(test["area"], test["crop"]) if (a, c) not in model.region_crop_mean_
    )
    print(f"Cold-start test rows (no training history for that region/crop): {cold_start}/{len(test)}")

    print(
        "\nInterpretation: this is the number every Phase 9 model (linear regression, "
        "decision tree, random forest) must beat using rainfall/temperature/pesticide "
        "features to be worth using over 'just look up the historical average.'"
    )
