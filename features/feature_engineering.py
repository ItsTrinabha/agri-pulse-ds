"""Phase 12 - Feature Engineering: the single, reusable feature pipeline
shared by the yield regressor (Phase 9) and risk classifier (Phase 10).

This formalizes and extends what started as a private class inside
models/yield_model.py (Phase 9) into its own pipeline stage, per the
project's directory structure - feature engineering is a distinct
concern from model training, worth its own module and its own tests.

Feature list and WHY each is available at prediction time (the Phase 12
exit criteria):
  - year                  : trivially known in advance.
  - rainfall_mm, avg_temp_c,
    pesticides_tonnes     : this SEASON's weather/practice data - in a
                             real deployment these would need to be
                             forecast/estimated rather than measured after
                             the fact, which is exactly why they're
                             median-imputed with a *_missing indicator
                             here rather than assumed always available.
  - crop                  : chosen by the farmer before planting - known.
  - region_mean_yield     : a train-only historical aggregate - known
                             before the season starts (target/mean
                             encoding for the high-cardinality `area`
                             column, chosen over one-hot for 212
                             categories - see Phase 9 D9.1).
  - lag1_yield            : last year's ALREADY-OBSERVED yield - known
                             before this year's season, unlike this
                             year's own yield (which would be leakage).
  - yield_trend_ratio     : lag1_yield / region_mean_yield - "is this
                             region trending above or below its own long-
                             run average," a ratio feature (Phase 12
                             "ratios" learn topic) - also only uses
                             already-observed history.
  - is_post_1990          : temporal feature encoding the structural break
                             found in Phase 6 (t-test, p~1e-165) and
                             Phase 7 Q5 (post-1990 = when rainfall/
                             pesticide coverage becomes usable) - known
                             from the year alone.

Nothing here reads yield_hg_ha for the CURRENT row - see
assert_no_target_leakage() below, which is run as a check, not just
asserted in a comment.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

POST_1990_CUTOFF = 1990


class FeatureBuilder:
    def fit(self, train: pd.DataFrame) -> "FeatureBuilder":
        self.medians_ = train[["rainfall_mm", "avg_temp_c", "pesticides_tonnes"]].median()
        self.region_mean_ = train.groupby("area")["yield_hg_ha"].mean()
        self.global_mean_ = train["yield_hg_ha"].mean()
        self.crops_ = sorted(train["crop"].unique())
        return self

    def _lag1_yield(self, df: pd.DataFrame, full_history: pd.DataFrame) -> pd.Series:
        """Look up (area, crop, year-1)'s yield from the full curated
        dataset (not just this split). Using last year's already-observed
        actual yield is legitimate - it would be genuinely known at
        prediction time - unlike using this year's own yield."""
        lookup = full_history.set_index(["area", "crop", "year"])["yield_hg_ha"]
        keys = list(zip(df["area"], df["crop"], df["year"] - 1))
        return pd.Series([lookup.get(k, np.nan) for k in keys], index=df.index)

    def transform(self, df: pd.DataFrame, full_history: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        out["year"] = df["year"]
        out["is_post_1990"] = (df["year"] >= POST_1990_CUTOFF).astype(int)

        for col in ["rainfall_mm", "avg_temp_c", "pesticides_tonnes"]:
            out[f"{col}_missing"] = df[col].isna().astype(int)
            out[col] = df[col].fillna(self.medians_[col])

        region_mean = df["area"].map(self.region_mean_).fillna(self.global_mean_)
        out["region_mean_yield"] = region_mean

        lag1 = self._lag1_yield(df, full_history)
        out["lag1_yield_missing"] = lag1.isna().astype(int)
        out["lag1_yield"] = lag1.fillna(region_mean)

        # Ratio feature: is this region-crop trending above/below its own
        # long-run average right now? >1 = trending up, <1 = trending down.
        out["yield_trend_ratio"] = out["lag1_yield"] / region_mean.replace(0, np.nan)
        out["yield_trend_ratio"] = out["yield_trend_ratio"].fillna(1.0)

        for crop in self.crops_:
            out[f"crop_{crop}"] = (df["crop"] == crop).astype(int)

        return out


def assert_no_target_leakage(feature_df: pd.DataFrame, target: pd.Series) -> None:
    """Practical leakage check, not just a doc comment:
    1. no engineered column is a byte-for-byte copy of the target.
    2. no engineered column has a suspiciously perfect (|r|>0.999)
       correlation with the target - a real feature can be strongly
       predictive, but a *perfect* correlation almost always means an
       indexing bug re-used the current row's own target value.
    """
    for col in feature_df.columns:
        if feature_df[col].equals(target.reset_index(drop=True)) or (feature_df[col].to_numpy() == target.to_numpy()).all():
            raise AssertionError(f"Leakage: feature '{col}' is identical to the target.")
        if pd.api.types.is_numeric_dtype(feature_df[col]) and feature_df[col].nunique() > 1:
            corr = np.corrcoef(feature_df[col].to_numpy(), target.to_numpy())[0, 1]
            if abs(corr) > 0.999:
                raise AssertionError(f"Leakage suspected: feature '{col}' has |r|={abs(corr):.4f} with the target.")
    print(f"Leakage check passed: {len(feature_df.columns)} features, none identical to or perfectly correlated with the target.")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")

    from models.baseline import CUTOFF_YEAR
    from models.evaluation import temporal_split

    train_raw, test_raw = temporal_split(df, CUTOFF_YEAR)
    fb = FeatureBuilder().fit(train_raw)
    X_train = fb.transform(train_raw, df)

    print(f"Engineered {len(X_train.columns)} features from {len(train_raw)} training rows:")
    print(list(X_train.columns))

    assert_no_target_leakage(X_train, train_raw["yield_hg_ha"])

    print("\nSample yield_trend_ratio distribution (1.0 = exactly at region's historical average):")
    print(X_train["yield_trend_ratio"].describe())
