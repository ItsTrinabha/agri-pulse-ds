"""Phase 5 - row-level business rules per source.

Each rule is (name, reason, check_fn) where check_fn(df) returns a boolean
Series that is True for the INVALID rows it flags (so multiple rules can
each mark their own set of bad rows, and a row can fail more than one
rule). This is the "invalid ranges / inconsistent categories / negative
values" part of spec section 4.2.

Deliberately NOT flagged as invalid here: nulls in weather/pesticide
values. A country-year a source doesn't cover is expected sparsity (see
docs/data_dictionary.md), not corruption - quarantining it would throw
away legitimate yield rows just because weather data happens not to
exist for that row yet. Missingness is measured (quality_report.py),
not punished.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

CURRENT_YEAR = 2026
# Deliberately permissive: this catches genuinely impossible years (0,
# negative, garbage far-future values), not "years outside what our yield
# analysis happens to cover" - temp.csv legitimately starts in 1743
# (real historical instrument records), which is a scoping question for
# the transform/merge step (Phase 3), not a data-validity defect. An
# earlier version of this rule used 1900 as the floor and wrongly rejected
# 31,981 genuine pre-1900 temperature readings as "invalid" - see D5.1.
MIN_PLAUSIBLE_YEAR = 1600

KNOWN_CROPS = {
    "Maize", "Potatoes", "Rice, paddy", "Wheat", "Sorghum",
    "Soybeans", "Cassava", "Yams", "Sweet potatoes", "Plantains and others",
}


@dataclass
class Rule:
    name: str
    reason: str
    check_fn: Callable[[pd.DataFrame], pd.Series]  # True = invalid


def _year_out_of_range(col: str) -> Callable[[pd.DataFrame], pd.Series]:
    def check(df: pd.DataFrame) -> pd.Series:
        return (df[col] < MIN_PLAUSIBLE_YEAR) | (df[col] > CURRENT_YEAR)
    return check


YIELD_RULES = [
    Rule("duplicate_row", "duplicate_row", lambda df: df.duplicated(keep="first")),
    Rule("year_out_of_range", "year_out_of_range", _year_out_of_range("Year")),
    Rule("non_positive_yield", "non_positive_yield", lambda df: pd.to_numeric(df["Value"], errors="coerce") <= 0),
    # 80 t/ha is a deliberately generous global ceiling (not crop-specific) -
    # see docs/decisions.md D5.2 for why a per-crop bound was not used.
    Rule("implausible_yield", "implausible_yield_over_800000_hg_ha", lambda df: pd.to_numeric(df["Value"], errors="coerce") > 800_000),
    Rule("unknown_crop", "unknown_crop_category", lambda df: ~df["Item"].isin(KNOWN_CROPS)),
    Rule("unexpected_unit", "unexpected_unit", lambda df: df["Unit"] != "hg/ha"),
]

PESTICIDES_RULES = [
    Rule("duplicate_row", "duplicate_row", lambda df: df.duplicated(keep="first")),
    Rule("year_out_of_range", "year_out_of_range", _year_out_of_range("Year")),
    Rule("negative_pesticide_use", "negative_pesticide_use", lambda df: pd.to_numeric(df["Value"], errors="coerce") < 0),
]

RAINFALL_RULES = [
    Rule("duplicate_row", "duplicate_row", lambda df: df.duplicated(keep="first")),
    Rule("year_out_of_range", "year_out_of_range", _year_out_of_range("Year")),
    # ".." sentinel -> NaN is applied before rules run; a genuinely negative
    # or absurd rainfall figure is what this catches (Death Valley-style
    # deserts can be ~0mm/yr; wettest recorded places are ~11,000+ mm/yr).
    Rule("implausible_rainfall", "implausible_rainfall", lambda df: (df["rainfall_numeric"] < 0) | (df["rainfall_numeric"] > 15_000)),
]

TEMP_RULES = [
    Rule("duplicate_row", "duplicate_row", lambda df: df.duplicated(keep="first")),
    Rule("year_out_of_range", "year_out_of_range", _year_out_of_range("year")),
    # Global recorded extremes: ~-89.2C (Vostok) to ~56.7C (Death Valley).
    Rule("implausible_temp", "implausible_temp", lambda df: (df["avg_temp"] < -90) | (df["avg_temp"] > 60)),
]

RULES_BY_SOURCE = {
    "yield": YIELD_RULES,
    "pesticides": PESTICIDES_RULES,
    "rainfall": RAINFALL_RULES,
    "temp": TEMP_RULES,
}
