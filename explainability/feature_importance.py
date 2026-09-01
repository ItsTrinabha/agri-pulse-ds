"""Phase 13 - Explainable AI: global feature importance (two methods,
compared) and a per-prediction explanation ("prediction explanation
screen") using the tuned Random Forest yield model from Phase 9/12.

Concept, stated once here because it governs every string this module
prints: a feature importance or SHAP value says "the model weighted this
feature this heavily when making this prediction." It does NOT say
"changing this feature in the real world would change the real yield by
this amount" - that would be a causal claim this dataset (correlational,
no experiment/randomization) cannot support. Every explanation below uses
"associated with" / "the model weighted," never "caused" or "drove up" -
spec section 6's explicit wording rule.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from sklearn.inspection import permutation_importance

from models.baseline import CUTOFF_YEAR
from models.evaluation import temporal_split


def compare_importance_methods(model, X_train, X_test, y_test, figures_dir: Path) -> pd.DataFrame:
    """Built-in (impurity-based) importance vs. permutation importance.
    Impurity-based importance is computed for free during training but is
    known to be biased toward high-cardinality/continuous features (it
    counts how often/effectively a feature is used to split, not whether
    that split actually helps on unseen data). Permutation importance
    instead measures the real test-set score drop when a feature's values
    are shuffled - slower, but a more trustworthy "does this feature
    actually matter" answer. Comparing both, rather than trusting one, is
    the Phase 13 "limitations" learning point made concrete."""
    impurity = pd.Series(model.feature_importances_, index=X_train.columns, name="impurity_importance")

    perm = permutation_importance(model, X_test, y_test, n_repeats=10, random_state=42, n_jobs=-1)
    permutation = pd.Series(perm.importances_mean, index=X_test.columns, name="permutation_importance")

    comparison = pd.concat([impurity, permutation], axis=1).sort_values("permutation_importance", ascending=False)

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    comparison["impurity_importance"].sort_values().plot(kind="barh", ax=axes[0], color="#4c8c4a")
    axes[0].set_title("Impurity-based importance (built-in, biased toward\nhigh-cardinality features)")
    comparison["permutation_importance"].sort_values().plot(kind="barh", ax=axes[1], color="#3a6ea5")
    axes[1].set_title("Permutation importance (test-set score drop\nwhen shuffled - more trustworthy)")
    fig.tight_layout()
    fig.savefig(figures_dir / "10_feature_importance_comparison.png", dpi=120)
    plt.close(fig)

    return comparison


def explain_one_prediction(model, X_test: pd.DataFrame, test_raw: pd.DataFrame, row_idx: int, figures_dir: Path, explainer: shap.TreeExplainer) -> None:
    """The "prediction explanation screen" (spec section 6's worked example
    format) for a single region-crop-year, via SHAP TreeExplainer - each
    feature's SHAP value is its signed contribution to THIS prediction,
    relative to the model's average prediction over the training data."""
    row = X_test.iloc[[row_idx]]
    context = test_raw.iloc[row_idx]
    prediction = model.predict(row)[0]

    shap_values = explainer(row)
    contributions = pd.Series(shap_values.values[0], index=row.columns).sort_values(key=abs, ascending=False)
    base_value = np.asarray(explainer.expected_value).reshape(-1)[0]

    print(f"\n=== Prediction explanation: {context['area']} / {context['crop']} / {context['year']} ===")
    print(f"Predicted yield: {prediction:,.0f} hg/ha (actual: {context['yield_hg_ha']:,.0f} hg/ha)")
    print(f"Base rate (average prediction over training data): {base_value:,.0f} hg/ha")
    print("\nTop factors the model weighted for this specific prediction (not causal claims):")
    for feat, contribution in contributions.head(6).items():
        direction = "pushed prediction UP" if contribution > 0 else "pushed prediction DOWN"
        print(f"  {feat} = {row[feat].iloc[0]:.2f}  ->  {direction} by {abs(contribution):,.0f} hg/ha (associated with, not caused by)")

    fig = plt.figure(figsize=(9, 5))
    shap.plots.waterfall(shap_values[0], max_display=8, show=False)
    plt.title(f"{context['area']} / {context['crop']} / {context['year']} - SHAP contribution breakdown", fontsize=10)
    plt.tight_layout()
    plt.savefig(figures_dir / f"11_shap_explanation_{context['area'].replace(' ', '_')}_{context['crop'].replace(', ', '_').replace(' ', '_')}_{context['year']}.png", dpi=120, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    figures_dir = project_root / "notebooks" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    artifact = joblib.load(project_root / "data" / "processed" / "yield_model.joblib")
    model, fb = artifact["model"], artifact["feature_builder"]

    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")
    train_raw, test_raw = temporal_split(df, CUTOFF_YEAR)
    X_train = fb.transform(train_raw, df)
    X_test = fb.transform(test_raw, df)
    y_test = test_raw["yield_hg_ha"].to_numpy()

    print("=== Global feature importance: impurity vs. permutation ===")
    comparison = compare_importance_methods(model, X_train, X_test, y_test, figures_dir)
    print(comparison.to_string())

    top_impurity = comparison["impurity_importance"].idxmax()
    top_permutation = comparison["permutation_importance"].idxmax()
    if top_impurity != top_permutation:
        print(
            f"\nNote the two methods disagree on the #1 feature ({top_impurity} vs {top_permutation}) - "
            "exactly the kind of discrepancy that makes trusting a single importance method risky."
        )
    else:
        print(f"\nBoth methods agree the top feature is '{top_impurity}'.")

    print("\n=== Per-prediction explanations (SHAP) ===")
    explainer = shap.TreeExplainer(model)

    # One high-yield example and one low-yield example, for contrast.
    sorted_by_yield = test_raw["yield_hg_ha"].sort_values()
    low_idx = X_test.index.get_loc(sorted_by_yield.index[len(sorted_by_yield) // 10])   # ~10th percentile
    high_idx = X_test.index.get_loc(sorted_by_yield.index[-(len(sorted_by_yield) // 10)])  # ~90th percentile

    explain_one_prediction(model, X_test, test_raw, low_idx, figures_dir, explainer)
    explain_one_prediction(model, X_test, test_raw, high_idx, figures_dir, explainer)

    print(f"\nSaved importance-comparison and SHAP waterfall charts to {figures_dir}")
    print(
        "\nReminder (spec section 6): every 'pushed prediction up/down' statement above describes what "
        "the MODEL weighted, not what caused the real-world yield outcome. This is a correlational "
        "dataset with no controlled experiment behind it - a strong SHAP contribution from rainfall "
        "means the model leaned on rainfall to make this prediction, not that rainfall is proven to "
        "drive yield in reality (see D6.2/D7.2's rainfall-yield confound for a concrete case of this)."
    )
