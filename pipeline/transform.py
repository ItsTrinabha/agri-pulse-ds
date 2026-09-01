"""Phase 3 - Pandas: load, inspect, clean, and merge the four raw sources
into the first curated agricultural dataset.

Concept: a pandas DataFrame is a table - like a spreadsheet, but every
column has one type and operations run across the whole column/table at
once (vectorized, same idea as Phase 2's NumPy arrays, because a DataFrame
is built on NumPy arrays under the hood).

This module is intentionally still "cleaning", not the formal Data Quality
Engine (that's Phase 5 - quarantine, reject-reason codes, a quality score).
Here we do the more basic pandas-mechanics version: fix types, drop exact
duplicate rows, normalize join keys, and merge - producing one dataset that
Phase 5 will later validate more rigorously.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RAINFALL_MISSING_SENTINEL = ".."

# Best-effort alias map: formal FAO/UN names -> the more common name used
# in the other sources. Not exhaustive - see docs/decisions.md (D3.2) for
# why this stays small rather than trying to solve country-name matching
# completely.
AREA_ALIASES = {
    "lao people's democratic republic": "laos",
    "viet nam": "vietnam",
    "bolivia (plurinational state of)": "bolivia",
    "venezuela (bolivarian republic of)": "venezuela",
    "republic of moldova": "moldova",
    "democratic republic of the congo": "democratic republic of congo",
    "congo": "congo",
    "iran (islamic republic of)": "iran",
    "republic of korea": "south korea",
    "democratic people's republic of korea": "north korea",
    "russian federation": "russia",
    "syrian arab republic": "syria",
    "united republic of tanzania": "tanzania",
    "china, taiwan province of": "taiwan",
    "brunei darussalam": "brunei",
    "the former yugoslav republic of macedonia": "macedonia",
    "united states of america": "united states",
    "united kingdom of great britain and northern ireland": "united kingdom",
    "czechia": "czech republic",
}


def normalize_area(name: str) -> str:
    """Lowercase + strip + apply the alias map. This is the join key used
    to match countries across sources with differently-formatted names."""
    key = name.strip().lower()
    return AREA_ALIASES.get(key, key)


def load_raw(name: str, raw_dir: Path) -> pd.DataFrame:
    return pd.read_csv(raw_dir / f"{name}.csv")


def clean_yield(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={"Area": "area", "Item": "crop", "Year": "year", "Value": "yield_hg_ha"})
    df = df[["area", "crop", "year", "yield_hg_ha"]].copy()
    df["area_key"] = df["area"].map(normalize_area)
    return df


def clean_pesticides(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={"Area": "area", "Year": "year", "Value": "pesticides_tonnes"})
    df = df[["area", "year", "pesticides_tonnes"]].copy()
    df["area_key"] = df["area"].map(normalize_area)
    return df


def clean_rainfall(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip()
    df = df.rename(columns={"Area": "area", "Year": "year", "average_rain_fall_mm_per_year": "rainfall_mm"})
    # ".." is FAO/World Bank's own "not available" sentinel, not the string "..".
    df["rainfall_mm"] = df["rainfall_mm"].replace(RAINFALL_MISSING_SENTINEL, pd.NA)
    df["rainfall_mm"] = pd.to_numeric(df["rainfall_mm"], errors="coerce")
    df = df[["area", "year", "rainfall_mm"]].copy()
    df["area_key"] = df["area"].map(normalize_area)
    return df


def clean_temp(df: pd.DataFrame) -> pd.DataFrame:
    """temp.csv turns out to be sub-annual (tens of readings per
    country-year, not one) despite the column being called avg_temp at
    yearly grain - confirmed by inspecting e.g. United States/1982, which
    has 41 distinct values ranging ~5-24C, a seasonal spread, not noise.
    Aggregate to one mean-per-(area, year) row before it can be joined at
    yearly grain, otherwise the merge fans out (found via a 121,936-row
    curated dataset when yield.csv alone has 56,717 rows - see D3.3)."""
    df = df.rename(columns={"country": "area", "year": "year", "avg_temp": "avg_temp_c"})
    before = len(df)
    df = df.drop_duplicates()
    dropped = before - len(df)
    if dropped:
        logger.info("temp: dropped %d exact duplicate rows", dropped)
    df = df[["area", "year", "avg_temp_c"]].copy()
    df["area_key"] = df["area"].map(normalize_area)
    # Group by (area_key, year) only - not area - so a spelling variant of
    # the same normalized country can't still leave two rows per key/year.
    df = df.groupby(["area_key", "year"], as_index=False).agg(
        area=("area", "first"), avg_temp_c=("avg_temp_c", "mean")
    )
    return df


def merge_sources(
    yield_df: pd.DataFrame,
    pesticides_df: pd.DataFrame,
    rainfall_df: pd.DataFrame,
    temp_df: pd.DataFrame,
) -> pd.DataFrame:
    """Left-join weather/practice sources onto yield (the finest-grained
    table: one row per area-crop-year). Weather/pesticide data doesn't vary
    by crop, so this is intentionally many-to-one on (area_key, year)."""
    merged = yield_df.merge(
        pesticides_df[["area_key", "year", "pesticides_tonnes"]],
        on=["area_key", "year"],
        how="left",
    )
    merged = merged.merge(
        rainfall_df[["area_key", "year", "rainfall_mm"]],
        on=["area_key", "year"],
        how="left",
    )
    merged = merged.merge(
        temp_df[["area_key", "year", "avg_temp_c"]],
        on=["area_key", "year"],
        how="left",
    )
    return merged.drop(columns=["area_key"])


def build_curated_dataset_from_frames(
    yield_raw: pd.DataFrame, pesticides_raw: pd.DataFrame, rainfall_raw: pd.DataFrame, temp_raw: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    """Clean + merge already-loaded raw source frames. Split out from
    build_curated_dataset() (Phase 15) so pipeline.py can pass in the
    Phase 5 Data Quality Engine's ACCEPTED rows instead of the untouched
    raw CSVs - closing the D6.1 gap (statistics/EDA/models were built on
    pre-quarantine data because nothing wired the two stages together)."""
    duplicate_report = {
        "yield": int(yield_raw.duplicated().sum()),
        "pesticides": int(pesticides_raw.duplicated().sum()),
        "rainfall": int(rainfall_raw.duplicated().sum()),
        "temp": int(temp_raw.duplicated().sum()),
    }
    null_report_raw = {
        "yield": yield_raw.isnull().sum().to_dict(),
        "pesticides": pesticides_raw.isnull().sum().to_dict(),
        "rainfall": rainfall_raw.isnull().sum().to_dict(),
        "temp": temp_raw.isnull().sum().to_dict(),
    }

    yield_df = clean_yield(yield_raw)
    pesticides_df = clean_pesticides(pesticides_raw)
    rainfall_df = clean_rainfall(rainfall_raw)
    temp_df = clean_temp(temp_raw)

    curated = merge_sources(yield_df, pesticides_df, rainfall_df, temp_df)

    match_report = {
        "total_rows": len(curated),
        "pesticides_matched_pct": round(100 * curated["pesticides_tonnes"].notna().mean(), 1),
        "rainfall_matched_pct": round(100 * curated["rainfall_mm"].notna().mean(), 1),
        "avg_temp_matched_pct": round(100 * curated["avg_temp_c"].notna().mean(), 1),
    }

    report = {
        "duplicate_rows_found_in_raw": duplicate_report,
        "null_counts_in_raw": null_report_raw,
        "join_match_rates": match_report,
    }
    return curated, report


def build_curated_dataset(raw_dir: Path) -> tuple[pd.DataFrame, dict]:
    """Standalone convenience wrapper: load straight from data/raw/ with no
    quality filtering (this is what Phase 3 originally did, kept working
    unmodified for direct `python -m pipeline.transform` runs). The
    orchestrated pipeline (pipeline/pipeline.py, Phase 15) instead calls
    build_curated_dataset_from_frames() with quality-ACCEPTED frames."""
    yield_raw = load_raw("yield", raw_dir)
    pesticides_raw = load_raw("pesticides", raw_dir)
    rainfall_raw = load_raw("rainfall", raw_dir)
    temp_raw = load_raw("temp", raw_dir)
    return build_curated_dataset_from_frames(yield_raw, pesticides_raw, rainfall_raw, temp_raw)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    raw_dir = project_root / "data" / "raw"
    processed_dir = project_root / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    curated, report = build_curated_dataset(raw_dir)

    out_path = processed_dir / "curated_dataset.csv"
    curated.to_csv(out_path, index=False)
    logger.info("Wrote curated dataset: %s (%d rows, %d columns)", out_path, *curated.shape)

    report_path = processed_dir / "_transform_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n=== Schema ===")
    print(curated.dtypes)

    print("\n=== Join match rates (curated rows with a non-null value from each source) ===")
    for k, v in report["join_match_rates"].items():
        print(f"  {k}: {v}")

    print("\n=== Yield statistics (hg/ha) ===")
    print(curated["yield_hg_ha"].describe())

    print("\n=== Average yield by crop ===")
    print(curated.groupby("crop")["yield_hg_ha"].mean().sort_values(ascending=False))

    print("\n=== Top 10 areas by average yield (all crops) ===")
    print(curated.groupby("area")["yield_hg_ha"].mean().sort_values(ascending=False).head(10))
