"""Phase 10 - Risk Classification: predict whether a (region, crop, year)
will UNDERPERFORM its crop's typical yield distribution.

Target definition (spec section 5, Model B, explicitly forbids inventing
an unrelated/unscientific target like "disease risk" from data that has
no disease information in it): "high risk" = 1 if yield_hg_ha falls below
that crop's 25th percentile, computed on TRAINING data only, per crop
(not a global percentile - a low Soybean yield and a low Potato yield are
different absolute numbers, per D7.3). This is a real, defensible,
data-grounded label: "did this region/crop/year underperform relative to
what's typical for that crop," not a fabricated agronomic diagnosis.

Reuses models/yield_model.py's FeatureBuilder features - none of them leak
the current row's own yield (lag1_yield is the *previous* year's, already
legitimately known; region_mean_yield is a train-only aggregate).
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from features.feature_engineering import FeatureBuilder
from models.baseline import CUTOFF_YEAR
from models.evaluation import temporal_split

RISK_PERCENTILE = 0.25


def compute_risk_thresholds(train: pd.DataFrame) -> dict[str, float]:
    """Per-crop 25th percentile of yield, computed on TRAIN ONLY. Applying
    a train-derived threshold to the test set (rather than recomputing on
    test) keeps "risk" meaning the same thing in both splits."""
    return train.groupby("crop")["yield_hg_ha"].quantile(RISK_PERCENTILE).to_dict()


def label_risk(df: pd.DataFrame, thresholds: dict[str, float]) -> np.ndarray:
    return (df["yield_hg_ha"] < df["crop"].map(thresholds)).astype(int).to_numpy()


def report_model(name: str, model, X_train, y_train, X_test, y_test) -> dict:
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else None

    accuracy = (preds == y_test).mean()
    auc = roc_auc_score(y_test, proba) if proba is not None else None

    print(f"\n{name}:")
    print(f"  accuracy: {accuracy:.4f}" + (f"   ROC-AUC: {auc:.4f}" if auc is not None else ""))
    print(classification_report(y_test, preds, target_names=["low_risk (0)", "high_risk (1)"], zero_division=0))
    cm = confusion_matrix(y_test, preds)
    print(f"  confusion matrix [[TN FP] [FN TP]]:\n{cm}")

    return {"name": name, "model": model, "accuracy": accuracy, "auc": auc, "confusion_matrix": cm}


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")

    train_raw, test_raw = temporal_split(df, CUTOFF_YEAR)

    thresholds = compute_risk_thresholds(train_raw)
    print("Per-crop risk thresholds (25th percentile of train yield, hg/ha):")
    for crop, t in thresholds.items():
        print(f"  {crop}: {t:,.0f}")

    y_train = label_risk(train_raw, thresholds)
    y_test = label_risk(test_raw, thresholds)
    print(f"\nClass balance - train: {y_train.mean():.1%} high-risk, test: {y_test.mean():.1%} high-risk")

    fb = FeatureBuilder().fit(train_raw)
    X_train = fb.transform(train_raw, df)
    X_test = fb.transform(test_raw, df)

    print("\n=== Why accuracy alone is misleading here ===")
    dummy = report_model(
        "Dummy classifier (always predicts majority class = low_risk)",
        DummyClassifier(strategy="most_frequent"),
        X_train, y_train, X_test, y_test,
    )
    print(
        f"  -> {dummy['accuracy']:.1%} accuracy by NEVER once correctly flagging a real high-risk case "
        "(recall for class 1 is exactly 0). A risk classifier that is 'usually right' but never "
        "catches the risk it exists to catch is useless - precision/recall/F1 on the minority class "
        "is what actually matters here, not accuracy."
    )

    # LogisticRegression's solver converges on gradient steps sized relative
    # to each feature's scale - "year" (~1961-2016) and yield-based features
    # (tens of thousands) are ~1000x apart, which made lbfgs fail to
    # converge within 1000 iterations. Tree models split on raw thresholds
    # per feature, so they're scale-invariant and don't need this.
    scaler = StandardScaler().fit(X_train)
    X_train_scaled = pd.DataFrame(scaler.transform(X_train), columns=X_train.columns, index=X_train.index)
    X_test_scaled = pd.DataFrame(scaler.transform(X_test), columns=X_test.columns, index=X_test.index)

    results = []
    results.append(report_model("Logistic Regression", LogisticRegression(max_iter=1000), X_train_scaled, y_train, X_test_scaled, y_test))
    results.append(report_model("Logistic Regression (class_weight=balanced)", LogisticRegression(max_iter=1000, class_weight="balanced"), X_train_scaled, y_train, X_test_scaled, y_test))
    results.append(report_model("Decision Tree", DecisionTreeClassifier(max_depth=8, random_state=42), X_train, y_train, X_test, y_test))
    rf_result = report_model("Random Forest", RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42, n_jobs=-1), X_train, y_train, X_test, y_test)
    results.append(rf_result)

    print("\n=== Summary (test set) ===")
    print(f"  {'model':45s} {'accuracy':>10s} {'ROC-AUC':>10s}")
    print(f"  {'Dummy (majority class)':45s} {dummy['accuracy']:>10.4f} {'n/a':>10s}")
    for r in results:
        auc_str = f"{r['auc']:.4f}" if r["auc"] is not None else "n/a"
        print(f"  {r['name']:45s} {r['accuracy']:>10.4f} {auc_str:>10s}")

    fig = ConfusionMatrixDisplay(rf_result["confusion_matrix"], display_labels=["low_risk", "high_risk"]).plot().figure_
    figures_dir = project_root / "notebooks" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(figures_dir / "07_risk_confusion_matrix.png", dpi=120, bbox_inches="tight")
    print(f"\nSaved Random Forest confusion matrix to {figures_dir / '07_risk_confusion_matrix.png'}")

    # Persist the class_weight=balanced Logistic Regression - the variant
    # chosen in D10.3 (higher recall on the minority/high-risk class, the
    # class that actually matters for a risk monitor) - plus everything
    # needed to score new rows: the scaler, the feature builder, and the
    # per-crop thresholds that define what "high risk" means (D10.1).
    balanced_model = [r["model"] for r in results if r["name"] == "Logistic Regression (class_weight=balanced)"][0]
    joblib.dump(
        {"model": balanced_model, "scaler": scaler, "feature_builder": fb, "risk_thresholds": thresholds},
        project_root / "data" / "processed" / "risk_model.joblib",
    )
    print(f"\nSaved risk model (class_weight=balanced Logistic Regression) to data/processed/risk_model.joblib (for Phase 20)")
