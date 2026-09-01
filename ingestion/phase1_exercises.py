"""Phase 1 practice exercises - plain Python (no pandas) over data/raw/yield.csv.

Each function is deliberately simple: the point of Phase 1 is being able to
do this without a library, so later (Phase 3) the pandas equivalent
(df.groupby("Area")["Value"].mean(), df["Value"].max()) is understood as a
shortcut for something you already know how to do by hand, not magic.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


def load_yield_records(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def average_yield(records: list[dict[str, str]], crop: str) -> float:
    """Exercise 1: calculate average yield for a given crop (hg/ha)."""
    values = [float(r["Value"]) for r in records if r["Item"] == crop]
    if not values:
        raise ValueError(f"No records found for crop '{crop}'")
    return sum(values) / len(values)


def maximum_yield(records: list[dict[str, str]], crop: str) -> dict[str, str]:
    """Exercise 2: find the single record with the maximum yield for a crop."""
    matches = [r for r in records if r["Item"] == crop]
    if not matches:
        raise ValueError(f"No records found for crop '{crop}'")
    return max(matches, key=lambda r: float(r["Value"]))


def group_average_yield_by_area(records: list[dict[str, str]], crop: str) -> dict[str, float]:
    """Exercise 3: group records by Area using a plain dict, then average per group.

    This is what pandas groupby does internally, one loop at a time.
    """
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for r in records:
        if r["Item"] != crop:
            continue
        area = r["Area"]
        totals[area] = totals.get(area, 0.0) + float(r["Value"])
        counts[area] = counts.get(area, 0) + 1
    return {area: totals[area] / counts[area] for area in totals}


def load_with_missing_file_handling(path: Path) -> list[dict[str, str]] | None:
    """Exercise 4: handle a missing file gracefully and report why."""
    try:
        return load_yield_records(path)
    except FileNotFoundError:
        print(f"Could not load '{path}': file does not exist. Skipping this source.")
        return None


def summary_to_json(summary: dict[str, float], out_path: Path) -> dict[str, float]:
    """Exercise 5: parse/write a JSON object (write then read back)."""
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with out_path.open("r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    yield_path = project_root / "data" / "raw" / "yield.csv"

    records = load_yield_records(yield_path)
    print(f"Loaded {len(records)} yield records")

    crop = "Maize"
    avg = average_yield(records, crop)
    print(f"\nAverage {crop} yield: {avg:.1f} hg/ha")

    top = maximum_yield(records, crop)
    print(f"Highest {crop} yield: {top['Value']} hg/ha in {top['Area']} ({top['Year']})")

    by_area = group_average_yield_by_area(records, crop)
    top5_areas = sorted(by_area.items(), key=lambda kv: kv[1], reverse=True)[:5]
    print(f"\nTop 5 areas by average {crop} yield:")
    for area, avg_val in top5_areas:
        print(f"  {area}: {avg_val:.1f} hg/ha")

    missing = load_with_missing_file_handling(project_root / "data" / "raw" / "does_not_exist.csv")
    print(f"\nMissing-file result: {missing}")

    out_path = project_root / "data" / "raw" / "_phase1_summary.json"
    roundtrip = summary_to_json({"crop": crop, "average_yield_hg_ha": round(avg, 2)}, out_path)
    print(f"\nJSON round-trip: {roundtrip}")
