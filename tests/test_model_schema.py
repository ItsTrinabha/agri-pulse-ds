"""Phase 21 - model input schema test: the trained model's expected
feature columns must exactly match what FeatureBuilder currently produces.
This is the regression guard against the class of bug where
feature_engineering.py changes (a column renamed/added/removed) but a
previously-trained model artifact silently goes stale - sklearn doesn't
error on an out-of-order or mismatched column set for many estimators, it
just produces garbage predictions.

Skips (not fails) if the model artifact doesn't exist - it's a derived,
gitignored file (see docs/decisions.md D4.1's "derived artifact" pattern),
not committed to the repo, so a fresh checkout won't have it until
`python -m models.yield_model` has been run once. That's a reproducibility
property worth stating explicitly, not silently working around.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "data" / "processed" / "yield_model.joblib"
CURATED_PATH = PROJECT_ROOT / "data" / "processed" / "curated_dataset.csv"

pytestmark = pytest.mark.skipif(
    not (MODEL_PATH.exists() and CURATED_PATH.exists()),
    reason="Derived artifacts not present - run `python -m pipeline.pipeline` then `python -m models.yield_model` first.",
)


def test_feature_builder_output_matches_model_expected_columns():
    artifact = joblib.load(MODEL_PATH)
    model, fb, expected_columns = artifact["model"], artifact["feature_builder"], artifact["feature_columns"]

    df = pd.read_csv(CURATED_PATH)
    sample = df.iloc[:5]
    features = fb.transform(sample, df)

    assert list(features.columns) == expected_columns, (
        "FeatureBuilder's output no longer matches the columns the saved model was trained on - "
        "the model needs retraining (python -m models.yield_model) before it can be trusted."
    )


def test_model_predicts_without_error_on_freshly_built_features():
    """A softer but still real check: even if column order matched, the
    model must actually accept the feature matrix shape without raising."""
    artifact = joblib.load(MODEL_PATH)
    model, fb = artifact["model"], artifact["feature_builder"]

    df = pd.read_csv(CURATED_PATH)
    sample = df.iloc[:5]
    features = fb.transform(sample, df)

    predictions = model.predict(features)
    assert len(predictions) == 5
    assert (predictions > 0).all()  # a yield prediction should never be non-positive
