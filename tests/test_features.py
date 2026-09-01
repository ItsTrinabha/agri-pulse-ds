"""Phase 21 - unit tests for features/feature_engineering.py: feature
calculations, and a POSITIVE test that assert_no_target_leakage() actually
catches a deliberately leaky feature (not just that it passes on good
data - a check that never fails on bad input isn't proving anything)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from features.feature_engineering import FeatureBuilder, assert_no_target_leakage


def _toy_dataset() -> pd.DataFrame:
    return pd.DataFrame({
        "area": ["Kenya", "Kenya", "Kenya", "Uganda"],
        "crop": ["Maize", "Maize", "Maize", "Maize"],
        "year": [2000, 2001, 2002, 2002],
        "yield_hg_ha": [10000, 12000, 11000, 9000],
        "rainfall_mm": [500.0, np.nan, 600.0, 550.0],
        "avg_temp_c": [20.0, 21.0, np.nan, 19.0],
        "pesticides_tonnes": [5.0, 6.0, 7.0, np.nan],
    })


def test_feature_builder_produces_expected_columns():
    df = _toy_dataset()
    fb = FeatureBuilder().fit(df)
    features = fb.transform(df, df)
    expected = {
        "year", "is_post_1990", "rainfall_mm_missing", "rainfall_mm",
        "avg_temp_c_missing", "avg_temp_c", "pesticides_tonnes_missing", "pesticides_tonnes",
        "region_mean_yield", "lag1_yield_missing", "lag1_yield", "yield_trend_ratio", "crop_Maize",
    }
    assert expected.issubset(set(features.columns))


def test_feature_builder_imputes_missing_values_no_nans_remain():
    df = _toy_dataset()
    fb = FeatureBuilder().fit(df)
    features = fb.transform(df, df)
    assert features[["rainfall_mm", "avg_temp_c", "pesticides_tonnes", "lag1_yield"]].isna().sum().sum() == 0


def test_feature_builder_missing_indicator_matches_original_nulls():
    df = _toy_dataset()
    fb = FeatureBuilder().fit(df)
    features = fb.transform(df, df)
    assert features["rainfall_mm_missing"].tolist() == df["rainfall_mm"].isna().astype(int).tolist()


def test_lag1_yield_uses_prior_year_actual_not_current_year():
    """Leakage-adjacent correctness check: Kenya/Maize/2001's lag1_yield
    must be 2000's yield (10000), never 2001's own yield (12000)."""
    df = _toy_dataset()
    fb = FeatureBuilder().fit(df)
    features = fb.transform(df, df)
    kenya_2001 = features[(df["area"] == "Kenya") & (df["year"] == 2001)]
    assert kenya_2001["lag1_yield"].iloc[0] == 10000


def test_lag1_yield_falls_back_to_region_mean_when_no_prior_year():
    """Kenya/2000 has no 1999 record - lag1_yield must fall back to the
    region mean, not be left NaN or silently zero."""
    df = _toy_dataset()
    fb = FeatureBuilder().fit(df)
    features = fb.transform(df, df)
    kenya_2000 = features[(df["area"] == "Kenya") & (df["year"] == 2000)]
    assert kenya_2000["lag1_yield_missing"].iloc[0] == 1
    assert not pd.isna(kenya_2000["lag1_yield"].iloc[0])


def test_assert_no_target_leakage_passes_on_real_features():
    df = _toy_dataset()
    fb = FeatureBuilder().fit(df)
    features = fb.transform(df, df)
    assert_no_target_leakage(features, df["yield_hg_ha"])  # must not raise


def test_assert_no_target_leakage_catches_identical_column():
    df = _toy_dataset()
    fb = FeatureBuilder().fit(df)
    features = fb.transform(df, df)
    leaky = features.copy()
    leaky["oops_the_target_itself"] = df["yield_hg_ha"].to_numpy()  # deliberate leak
    with pytest.raises(AssertionError, match="Leakage"):
        assert_no_target_leakage(leaky, df["yield_hg_ha"])


def test_assert_no_target_leakage_catches_near_perfect_correlation():
    df = _toy_dataset()
    fb = FeatureBuilder().fit(df)
    features = fb.transform(df, df)
    leaky = features.copy()
    leaky["suspicious_scaled_target"] = df["yield_hg_ha"].to_numpy() * 2.0 + 1  # perfectly correlated, not identical
    with pytest.raises(AssertionError, match="Leakage suspected"):
        assert_no_target_leakage(leaky, df["yield_hg_ha"])
