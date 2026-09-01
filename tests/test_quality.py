"""Phase 21 - unit tests for the Data Quality Engine (quality/). Each test
crafts a small DataFrame with one deliberate defect and checks the engine
catches exactly that defect - not "does the whole pipeline run," but "does
this specific rule do what its name says.\""""

from __future__ import annotations

import pandas as pd

from quality.schema_checks import SCHEMAS, validate_schema
from quality.validation_rules import RULES_BY_SOURCE, MIN_PLAUSIBLE_YEAR


def test_validate_schema_passes_with_all_required_columns():
    df = pd.DataFrame(columns=SCHEMAS["pesticides"].required_columns)
    result = validate_schema(df, SCHEMAS["pesticides"])
    assert result.passed
    assert result.missing_columns == []


def test_validate_schema_fails_with_missing_column():
    df = pd.DataFrame(columns=["Domain", "Area"])  # missing Element/Item/Year/Unit/Value
    result = validate_schema(df, SCHEMAS["pesticides"])
    assert not result.passed
    assert "Value" in result.missing_columns


def test_validate_schema_strips_column_whitespace():
    """rainfall.csv's real header has a leading space (' Area') - schema
    validation must not treat that as a missing column."""
    df = pd.DataFrame(columns=[" Area", "Year", "average_rain_fall_mm_per_year"])
    result = validate_schema(df, SCHEMAS["rainfall"])
    assert result.passed


def test_yield_rule_catches_non_positive_yield():
    df = pd.DataFrame({
        "Domain Code": ["QC"], "Domain": ["Crops"], "Area Code": [1], "Area": ["Kenya"],
        "Element Code": [1], "Element": ["Yield"], "Item Code": [1], "Item": ["Maize"],
        "Year Code": [2000], "Year": [2000], "Unit": ["hg/ha"], "Value": [0],
    })
    rule = next(r for r in RULES_BY_SOURCE["yield"] if r.name == "non_positive_yield")
    assert rule.check_fn(df).iloc[0]  # flagged as invalid


def test_yield_rule_accepts_positive_yield():
    df = pd.DataFrame({"Value": [15000]})
    rule = next(r for r in RULES_BY_SOURCE["yield"] if r.name == "non_positive_yield")
    assert not rule.check_fn(df).iloc[0]


def test_yield_rule_catches_implausible_high_yield():
    df = pd.DataFrame({"Value": [1_000_000]})  # the actual D3.4/D5.3 Kenya/Plantains record
    rule = next(r for r in RULES_BY_SOURCE["yield"] if r.name == "implausible_yield")
    assert rule.check_fn(df).iloc[0]


def test_yield_rule_catches_unknown_crop():
    df = pd.DataFrame({"Item": ["NotARealCrop"]})
    rule = next(r for r in RULES_BY_SOURCE["yield"] if r.name == "unknown_crop")
    assert rule.check_fn(df).iloc[0]


def test_duplicate_row_rule_flags_second_occurrence_only():
    df = pd.DataFrame({"a": [1, 1, 2], "b": [2, 2, 3]})
    rule = next(r for r in RULES_BY_SOURCE["yield"] if r.name == "duplicate_row")
    flags = rule.check_fn(df)
    assert list(flags) == [False, True, False]  # first occurrence kept, second flagged


def test_temp_rule_year_floor_permits_genuine_historical_data():
    """D5.1 regression test: an earlier version of this rule used 1900 as
    the floor and wrongly rejected 31,981 genuine pre-1900 temp.csv
    records. The floor must permit temp.csv's real 1743 start."""
    assert MIN_PLAUSIBLE_YEAR <= 1743
    df = pd.DataFrame({"year": [1750]})
    rule = next(r for r in RULES_BY_SOURCE["temp"] if r.name == "year_out_of_range")
    assert not rule.check_fn(df).iloc[0]  # 1750 must NOT be flagged as invalid


def test_temp_rule_catches_impossible_year():
    df = pd.DataFrame({"year": [-5]})
    rule = next(r for r in RULES_BY_SOURCE["temp"] if r.name == "year_out_of_range")
    assert rule.check_fn(df).iloc[0]


def test_temp_rule_catches_implausible_temperature():
    df = pd.DataFrame({"avg_temp": [500.0]})  # far outside -90..60C recorded extremes
    rule = next(r for r in RULES_BY_SOURCE["temp"] if r.name == "implausible_temp")
    assert rule.check_fn(df).iloc[0]
