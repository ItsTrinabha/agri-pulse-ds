"""Phase 9 - Yield Prediction: Linear Regression, Decision Tree, and Random
Forest compared against the Phase 8 baseline, plus a cross-validated
Random Forest, an overfitting demo, and a regularization demo.

Feature engineering moved to features/feature_engineering.py (Phase 12) -
see that module's docstring for the full feature list and the "available
at prediction time" reasoning behind each one.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.tree import DecisionTreeRegressor

from features.feature_engineering import FeatureBuilder
from models.baseline import CUTOFF_YEAR, HistoricalAverageBaseline
from models.evaluation import evaluate, temporal_split


def train_and_report(name: str, model, X_train, y_train, X_test, y_test) -> dict:
    model.fit(X_train, y_train)
    train_metrics = evaluate(y_train, model.predict(X_train))
    test_metrics = evaluate(y_test, model.predict(X_test))
    print(f"{name}:")
    print(f"  train: {train_metrics}")
    print(f"  test:  {test_metrics}")
    return {"name": name, "model": model, "train": train_metrics, "test": test_metrics}


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")

    train_raw, test_raw = temporal_split(df, CUTOFF_YEAR)

    fb = FeatureBuilder().fit(train_raw)
    X_train = fb.transform(train_raw, df)
    X_test = fb.transform(test_raw, df)
    y_train = train_raw["yield_hg_ha"].to_numpy()
    y_test = test_raw["yield_hg_ha"].to_numpy()

    print(f"Features: {list(X_train.columns)}\n")

    results = []

    baseline = HistoricalAverageBaseline().fit(train_raw)
    baseline_test = evaluate(y_test, baseline.predict(test_raw))
    print(f"Baseline (Phase 8, historical average): test: {baseline_test}\n")
    results.append({"name": "baseline", "test": baseline_test})

    results.append(train_and_report("Linear Regression", LinearRegression(), X_train, y_train, X_test, y_test))

    print()
    print("--- Regularization demo: Linear Regression vs. Ridge(alpha=10) ---")
    lr = LinearRegression().fit(X_train, y_train)
    ridge = Ridge(alpha=10.0).fit(X_train, y_train)
    print(f"  LinearRegression coefficient L2 norm: {np.linalg.norm(lr.coef_):,.1f}")
    print(f"  Ridge coefficient L2 norm:            {np.linalg.norm(ridge.coef_):,.1f}")
    print("  -> Ridge's L2 penalty shrinks coefficients toward zero, trading a little train fit for less variance.\n")

    print("--- Overfitting demo: unconstrained vs. depth-limited Decision Tree ---")
    results.append(train_and_report("Decision Tree (unconstrained)", DecisionTreeRegressor(random_state=42), X_train, y_train, X_test, y_test))
    results.append(train_and_report("Decision Tree (max_depth=8)", DecisionTreeRegressor(max_depth=8, random_state=42), X_train, y_train, X_test, y_test))
    print(
        "  -> the unconstrained tree's train R2 is far above its test R2 (memorized training noise, i.e. "
        "overfit); the depth-limited tree gives up some train fit but the train/test gap shrinks.\n"
    )

    print("--- Cross-validated Random Forest hyperparameter search (TimeSeriesSplit, respects time order) ---")
    tscv = TimeSeriesSplit(n_splits=4)
    param_grid = [
        {"n_estimators": 100, "max_depth": 8},
        {"n_estimators": 200, "max_depth": 12},
        {"n_estimators": 200, "max_depth": None},
    ]
    best_params, best_cv_mae = None, float("inf")
    for params in param_grid:
        fold_maes = []
        for fold_train_idx, fold_val_idx in tscv.split(X_train):
            model = RandomForestRegressor(random_state=42, n_jobs=-1, **params)
            model.fit(X_train.iloc[fold_train_idx], y_train[fold_train_idx])
            preds = model.predict(X_train.iloc[fold_val_idx])
            fold_maes.append(evaluate(y_train[fold_val_idx], preds).mae)
        mean_mae = float(np.mean(fold_maes))
        print(f"  {params}: mean CV MAE = {mean_mae:,.1f}")
        if mean_mae < best_cv_mae:
            best_cv_mae, best_params = mean_mae, params

    print(f"  Best params: {best_params} (CV MAE={best_cv_mae:,.1f})\n")

    rf_result = train_and_report(
        f"Random Forest (tuned: {best_params})",
        RandomForestRegressor(random_state=42, n_jobs=-1, **best_params),
        X_train, y_train, X_test, y_test,
    )
    results.append(rf_result)

    print("\n=== Summary: test-set performance vs. baseline ===")
    for r in results:
        print(f"  {r['name']}: {r['test']}")

    models_dir = project_root / "data" / "processed"
    joblib.dump(
        {"model": rf_result["model"], "feature_builder": fb, "feature_columns": list(X_train.columns)},
        models_dir / "yield_model.joblib",
    )
    print(f"\nSaved tuned Random Forest model to {models_dir / 'yield_model.joblib'} (for Phase 13/14)")
