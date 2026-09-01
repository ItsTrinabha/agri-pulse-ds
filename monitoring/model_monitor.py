"""Phase 18 - Model Monitoring: model versioning metadata, feature/
prediction drift detection, and performance-over-time tracking for the
Phase 9/12 yield model.

Concept: a model's test-set R²=0.95 is a snapshot from the day it was
evaluated. The world it's predicting into keeps moving - input
distributions shift (data drift), the relationship between inputs and the
target shifts (concept drift, shows up as performance drift), and neither
is visible unless someone is actually watching for it after deployment.

Honesty note (spec: "do not overclaim production-grade MLOps"): this is
NOT a live monitoring system - it has no scheduler, no alerting, no real
new incoming data. It re-uses the existing train (pre-2005) vs. test
(2005+) split as a legitimate, real stand-in for "reference period" vs.
"a later period" - both are genuine historical data, not fabricated -
which is enough to demonstrate the actual mechanics (PSI, KS-test,
performance-by-period) without pretending a scheduled production job
exists here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy import stats

from models.baseline import CUTOFF_YEAR
from models.evaluation import evaluate, temporal_split

DRIFT_FEATURES = ["rainfall_mm", "avg_temp_c", "pesticides_tonnes", "lag1_yield"]

# Standard PSI interpretation thresholds (industry convention, not derived
# from this dataset specifically).
PSI_NO_SHIFT = 0.1
PSI_MODERATE_SHIFT = 0.25


def population_stability_index(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """PSI: bin the REFERENCE distribution into deciles, then compare what
    fraction of each population falls in each bin. Large differences in
    bin proportions -> the current distribution has shifted from what the
    model was trained on."""
    reference = reference.dropna()
    current = current.dropna()
    breakpoints = np.quantile(reference, np.linspace(0, 1, bins + 1))
    breakpoints[0], breakpoints[-1] = -np.inf, np.inf  # catch values outside the reference's observed range

    ref_counts, _ = np.histogram(reference, bins=breakpoints)
    cur_counts, _ = np.histogram(current, bins=breakpoints)

    ref_pct = np.clip(ref_counts / ref_counts.sum(), 1e-6, None)
    cur_pct = np.clip(cur_counts / cur_counts.sum(), 1e-6, None)

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def feature_drift_report(reference: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in DRIFT_FEATURES:
        psi = population_stability_index(reference[col], current[col])
        ks_stat, ks_p = stats.ks_2samp(reference[col].dropna(), current[col].dropna())
        rows.append({
            "feature": col,
            "psi": round(psi, 4),
            "psi_interpretation": (
                "no significant shift" if psi < PSI_NO_SHIFT
                else "moderate shift" if psi < PSI_MODERATE_SHIFT
                else "significant shift"
            ),
            "ks_statistic": round(ks_stat, 4),
            "ks_pvalue": ks_p,
            "reference_mean": round(reference[col].mean(), 2),
            "current_mean": round(current[col].mean(), 2),
        })
    return pd.DataFrame(rows)


def prediction_drift(reference_preds: np.ndarray, current_preds: np.ndarray) -> dict:
    psi = population_stability_index(pd.Series(reference_preds), pd.Series(current_preds))
    ks_stat, ks_p = stats.ks_2samp(reference_preds, current_preds)
    return {
        "psi": round(psi, 4),
        "psi_interpretation": "no significant shift" if psi < PSI_NO_SHIFT else "moderate shift" if psi < PSI_MODERATE_SHIFT else "significant shift",
        "ks_statistic": round(ks_stat, 4),
        "ks_pvalue": ks_p,
        "reference_mean": round(float(reference_preds.mean()), 1),
        "current_mean": round(float(current_preds.mean()), 1),
    }


def performance_by_period(model, X_test: pd.DataFrame, test_raw: pd.DataFrame, bucket_years: int = 3) -> pd.DataFrame:
    """MAE/RMSE/R2 for each N-year bucket of the test period - does
    accuracy hold up further from the training cutoff, or decay?"""
    years = test_raw["year"]
    bucket_start = (years // bucket_years) * bucket_years
    rows = []
    for bucket, idx in test_raw.groupby(bucket_start).groups.items():
        y_true = test_raw.loc[idx, "yield_hg_ha"].to_numpy()
        y_pred = model.predict(X_test.loc[idx])
        m = evaluate(y_true, y_pred)
        rows.append({"period_start": int(bucket), "n": m.n, "mae": round(m.mae, 1), "rmse": round(m.rmse, 1), "r2": round(m.r2, 4)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    artifact = joblib.load(project_root / "data" / "processed" / "yield_model.joblib")
    model, fb = artifact["model"], artifact["feature_builder"]

    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")
    train_raw, test_raw = temporal_split(df, CUTOFF_YEAR)
    X_train = fb.transform(train_raw, df)
    X_test = fb.transform(test_raw, df)

    # --- Model versioning metadata ---
    model_card = {
        "model_version": "yield_rf_v1",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": type(model).__name__,
        "hyperparameters": model.get_params(),
        "feature_columns": list(X_train.columns),
        "training_rows": len(X_train),
        "training_year_range": [int(train_raw["year"].min()), int(train_raw["year"].max())],
        "test_metrics_at_training_time": evaluate(test_raw["yield_hg_ha"].to_numpy(), model.predict(X_test)).__dict__,
    }
    model_card_path = project_root / "data" / "processed" / "yield_model_card.json"
    with model_card_path.open("w", encoding="utf-8") as f:
        json.dump(model_card, f, indent=2, default=str)
    print(f"=== Model card written to {model_card_path} ===")
    print(f"version={model_card['model_version']}  algorithm={model_card['algorithm']}  "
          f"trained on {model_card['training_rows']} rows ({model_card['training_year_range']})")

    # --- Feature drift: reference = train period, current = test period ---
    print("\n=== Feature drift: train (reference) vs. test (current) period ===")
    drift = feature_drift_report(X_train, X_test)
    print(drift.to_string(index=False))

    # --- Prediction drift: early vs. late test period ---
    print("\n=== Prediction drift: 2005-2010 vs. 2011-2016 predictions ===")
    early_mask = test_raw["year"] <= 2010
    early_preds = model.predict(X_test[early_mask])
    late_preds = model.predict(X_test[~early_mask])
    pred_drift = prediction_drift(early_preds, late_preds)
    for k, v in pred_drift.items():
        print(f"  {k}: {v}")

    # --- Performance drift over time ---
    print("\n=== Performance by 3-year period within the test set ===")
    perf = performance_by_period(model, X_test, test_raw)
    print(perf.to_string(index=False))

    r2_trend = perf["r2"].iloc[-1] - perf["r2"].iloc[0]
    print(
        f"\nR2 changed by {r2_trend:+.4f} from the first to the last test-period bucket "
        f"({'held up' if abs(r2_trend) < 0.02 else 'degraded' if r2_trend < 0 else 'improved'} "
        "over the 12-year test window)."
    )

    # --- Simple, explainable retraining trigger rule ---
    print("\n=== Retraining trigger rule (illustrative, not a live alert system) ===")
    significant_drift_features = drift[drift["psi"] >= PSI_MODERATE_SHIFT]["feature"].tolist()
    performance_degraded = perf["r2"].min() < 0.85  # arbitrary but stated threshold, not hidden
    if significant_drift_features or performance_degraded:
        print(f"FLAG FOR RETRAINING: drifted features={significant_drift_features}, "
              f"min test-period R2={perf['r2'].min():.4f} (threshold 0.85)")
    else:
        print(f"No retraining flag: no feature exceeded PSI={PSI_MODERATE_SHIFT}, "
              f"min test-period R2={perf['r2'].min():.4f} stayed above 0.85.")
