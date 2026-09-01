"""Phase 21 - unit tests for pipeline/transform.py, on small synthetic
DataFrames (not the real dataset - fast, deterministic, and each test
isolates exactly one transformation behavior)."""

from __future__ import annotations

import pandas as pd

from pipeline.transform import (
    clean_rainfall,
    clean_temp,
    clean_yield,
    merge_sources,
    normalize_area,
)


def test_normalize_area_applies_alias_and_case():
    assert normalize_area("Viet Nam") == "vietnam"
    assert normalize_area("  FRANCE  ") == "france"


def test_clean_rainfall_converts_missing_sentinel_to_nan():
    raw = pd.DataFrame({" Area": ["Chad", "Chad"], "Year": [2000, 2001], "average_rain_fall_mm_per_year": ["..", "450"]})
    cleaned = clean_rainfall(raw)
    assert cleaned["rainfall_mm"].isna().sum() == 1
    assert cleaned.loc[cleaned["year"] == 2001, "rainfall_mm"].iloc[0] == 450.0


def test_clean_temp_aggregates_subannual_readings_to_one_row_per_area_year():
    """D3.3: temp.csv has multiple readings per (area, year) - clean_temp
    must collapse them to exactly one row per (area, year) via mean, or a
    downstream join will fan out (the actual bug D3.3 documents)."""
    raw = pd.DataFrame({
        "year": [2000, 2000, 2000, 2001],
        "country": ["Kenya", "Kenya", "Kenya", "Kenya"],
        "avg_temp": [20.0, 22.0, 24.0, 21.0],
    })
    cleaned = clean_temp(raw)
    assert len(cleaned) == 2  # (Kenya, 2000) and (Kenya, 2001), not 4
    row_2000 = cleaned[cleaned["year"] == 2000].iloc[0]
    assert row_2000["avg_temp_c"] == 22.0  # mean of 20, 22, 24


def test_clean_temp_drops_exact_duplicate_rows():
    raw = pd.DataFrame({
        "year": [2000, 2000],
        "country": ["Kenya", "Kenya"],
        "avg_temp": [20.0, 20.0],  # identical row, twice
    })
    cleaned = clean_temp(raw)
    assert len(cleaned) == 1


def test_merge_sources_preserves_yield_row_count_given_deduplicated_inputs():
    """merge_sources' contract is: given weather/practice sources already
    at (area_key, year) grain - which is what clean_temp/clean_rainfall/
    clean_pesticides guarantee - the merge doesn't fan out. (It is NOT
    merge_sources' job to deduplicate; that's clean_temp's, see the
    dedicated test below - this test would correctly FAIL if given
    duplicate-keyed input, which is exactly what happened before the D3.3
    fix and why that fix belongs in clean_temp, not the join.)"""
    yield_df = clean_yield(pd.DataFrame({
        "Area": ["Kenya", "Kenya"], "Item": ["Maize", "Wheat"], "Year": [2000, 2000], "Value": [1000, 2000],
    }))
    pesticides_df = pd.DataFrame({"area": [], "area_key": [], "year": [], "pesticides_tonnes": []})
    rainfall_df = pd.DataFrame({"area": [], "area_key": [], "year": [], "rainfall_mm": []})
    temp_df = pd.DataFrame({"area": ["Kenya"], "area_key": ["kenya"], "year": [2000], "avg_temp_c": [21.0]})  # one row per (area_key, year)

    merged = merge_sources(yield_df, pesticides_df, rainfall_df, temp_df)
    assert len(merged) == 2  # matches yield_df's row count exactly


def test_merge_sources_fans_out_if_given_undeduplicated_input():
    """The inverse of the test above, kept deliberately: proves
    merge_sources by itself provides NO fan-out protection - that
    protection is entirely clean_temp's responsibility (D3.3). If this
    test ever starts failing (i.e. merge_sources stops fanning out on
    duplicate keys), the comment above describing the division of
    responsibility is now wrong and needs updating, not this test."""
    yield_df = clean_yield(pd.DataFrame({
        "Area": ["Kenya"], "Item": ["Maize"], "Year": [2000], "Value": [1000],
    }))
    pesticides_df = pd.DataFrame({"area": [], "area_key": [], "year": [], "pesticides_tonnes": []})
    rainfall_df = pd.DataFrame({"area": [], "area_key": [], "year": [], "rainfall_mm": []})
    temp_df = pd.DataFrame({"area": ["Kenya", "Kenya"], "area_key": ["kenya", "kenya"], "year": [2000, 2000], "avg_temp_c": [20.0, 22.0]})

    merged = merge_sources(yield_df, pesticides_df, rainfall_df, temp_df)
    assert len(merged) == 2  # fanned out from 1 yield row to 2, because temp_df wasn't deduplicated first


def test_clean_yield_renames_and_selects_expected_columns():
    raw = pd.DataFrame({
        "Domain Code": ["QC"], "Domain": ["Crops"], "Area Code": [1], "Area": ["Kenya"],
        "Element Code": [1], "Element": ["Yield"], "Item Code": [1], "Item": ["Maize"],
        "Year Code": [2000], "Year": [2000], "Unit": ["hg/ha"], "Value": [1000],
    })
    cleaned = clean_yield(raw)
    assert list(cleaned.columns) == ["area", "crop", "year", "yield_hg_ha", "area_key"]
    assert cleaned["yield_hg_ha"].iloc[0] == 1000
