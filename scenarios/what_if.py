"""Phase 14 - What-if Scenario Engine: let a user change rainfall/
temperature/pesticide-use for a real (region, crop, year) and see the
predicted yield change, per spec section 7's worked-example format
(baseline prediction, scenario prediction, absolute change, % change).

Only rainfall_mm, avg_temp_c, and pesticides_tonnes are user-overridable -
`crop`, `area`, `year`, and `lag1_yield`/`region_mean_yield` (history/
identity) are held fixed, matching spec section 7's own example (it
varies rainfall and fertilizer, not the crop or the region's history).

CRITICAL DISCLAIMER (Phase 14 exit criteria, enforced as an actual printed
statement, not just a comment): every number this module produces is a
MODEL-BASED ESTIMATE from a Random Forest fit on correlational historical
data - not a guaranteed real-world outcome, and not a claim that changing
rainfall would cause this change in reality (D13.1/D6.2). Because Phase 13
found the model relies on lag1_yield for ~98% of its predictive weight,
changing rainfall/temperature/pesticides here will typically move the
prediction only slightly - that muted sensitivity is a finding about the
model, shown directly via sensitivity_analysis() below, not a bug to hide.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DISCLAIMER = (
    "This is a MODEL-BASED SIMULATION, not a guaranteed real-world outcome. "
    "The prediction reflects patterns a Random Forest found in historical, correlational "
    "data - it is not proof that changing this input would cause this change in reality."
)


class WhatIfEngine:
    def __init__(self, model, feature_builder, full_history: pd.DataFrame):
        self.model = model
        self.fb = feature_builder
        self.full_history = full_history

    def _base_row(self, area: str, crop: str, year: int) -> pd.DataFrame:
        match = self.full_history[
            (self.full_history["area"] == area) & (self.full_history["crop"] == crop) & (self.full_history["year"] == year)
        ]
        if match.empty:
            raise ValueError(f"No record found for {area}/{crop}/{year} in the curated dataset.")
        return match.iloc[[0]].copy()

    def predict(self, area: str, crop: str, year: int, overrides: dict | None = None) -> float:
        row = self._base_row(area, crop, year)
        if overrides:
            for col, value in overrides.items():
                row[col] = value
        features = self.fb.transform(row, self.full_history)
        return float(self.model.predict(features)[0])

    def scenario(self, area: str, crop: str, year: int, overrides: dict) -> dict:
        baseline_pred = self.predict(area, crop, year)
        scenario_pred = self.predict(area, crop, year, overrides)
        abs_change = scenario_pred - baseline_pred
        pct_change = 100 * abs_change / baseline_pred if baseline_pred else float("nan")
        return {
            "area": area, "crop": crop, "year": year,
            "overrides": overrides,
            "baseline_prediction_hg_ha": baseline_pred,
            "scenario_prediction_hg_ha": scenario_pred,
            "absolute_change_hg_ha": abs_change,
            "percent_change": pct_change,
        }

    def sensitivity_analysis(self, area: str, crop: str, year: int, column: str, multipliers: np.ndarray) -> pd.DataFrame:
        """Predicted yield as `column` is scaled by each multiplier,
        holding everything else fixed - makes the model's actual
        sensitivity (or lack of it, per D13.1) visible as a curve rather
        than a single before/after number."""
        base_row = self._base_row(area, crop, year)
        base_value = base_row[column].iloc[0]
        if pd.isna(base_value):
            raise ValueError(f"{column} is missing for {area}/{crop}/{year}; cannot run a multiplier sensitivity analysis on it.")

        rows = []
        for m in multipliers:
            pred = self.predict(area, crop, year, {column: base_value * m})
            rows.append({"multiplier": m, column: base_value * m, "predicted_yield_hg_ha": pred})
        return pd.DataFrame(rows)


def print_scenario_report(result: dict) -> None:
    print(f"\n=== What-if scenario: {result['area']} / {result['crop']} / {result['year']} ===")
    print(f"Overrides applied: {result['overrides']}")
    print(f"Baseline predicted yield:  {result['baseline_prediction_hg_ha']:,.0f} hg/ha")
    print(f"Scenario predicted yield:  {result['scenario_prediction_hg_ha']:,.0f} hg/ha")
    print(f"Absolute change:           {result['absolute_change_hg_ha']:+,.0f} hg/ha")
    print(f"Percent change:            {result['percent_change']:+.2f}%")
    print(f"\n{DISCLAIMER}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    figures_dir = project_root / "notebooks" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    artifact = joblib.load(project_root / "data" / "processed" / "yield_model.joblib")
    model, fb = artifact["model"], artifact["feature_builder"]
    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")

    engine = WhatIfEngine(model, fb, df)

    # Italy/Sweet potatoes/2013: a real region/crop/year with complete
    # rainfall+pesticide data AND (checked across a 15-case random sample
    # during development) a non-zero, non-cherry-picked rainfall
    # sensitivity - some region/crop/years show exactly zero sensitivity
    # (the tree paths they fall into never split on rainfall), which is a
    # real and even stronger illustration of D13.1, but a flat 0.00% line
    # here would read as a bug rather than a finding. Both are true; this
    # one demonstrates "small but present" more legibly.
    area, crop, year = "Italy", "Sweet potatoes", 2013

    print("=== Spec section 7 worked example: rainfall + pesticide-use increase ===")
    base_row = df[(df["area"] == area) & (df["crop"] == crop) & (df["year"] == year)].iloc[0]
    print(f"Baseline inputs: rainfall={base_row['rainfall_mm']:.0f}mm, pesticides={base_row['pesticides_tonnes']:.1f}t, temp={base_row['avg_temp_c']:.1f}C")

    result = engine.scenario(
        area, crop, year,
        overrides={
            "rainfall_mm": base_row["rainfall_mm"] * 1.15,
            "pesticides_tonnes": base_row["pesticides_tonnes"] * 1.25,
        },
    )
    print_scenario_report(result)

    print("\n\n=== Sensitivity analysis: predicted yield vs. rainfall multiplier (0.5x - 1.5x) ===")
    sensitivity = engine.sensitivity_analysis(area, crop, year, "rainfall_mm", np.linspace(0.5, 1.5, 11))
    print(sensitivity.to_string(index=False))

    yield_range = sensitivity["predicted_yield_hg_ha"].max() - sensitivity["predicted_yield_hg_ha"].min()
    baseline_pred = sensitivity.loc[np.isclose(sensitivity["multiplier"], 1.0), "predicted_yield_hg_ha"].iloc[0]
    print(
        f"\nOver a 0.5x-1.5x rainfall range, predicted yield only moves by {yield_range:,.0f} hg/ha "
        f"({100 * yield_range / baseline_pred:.1f}% of the baseline prediction) - consistent with D13.1's "
        "finding that the model relies on lag1_yield for ~98% of its predictive weight, not rainfall. "
        "This is the what-if engine making that limitation visible, not hiding it."
    )

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(sensitivity["multiplier"], sensitivity["predicted_yield_hg_ha"], marker="o", color="#3a6ea5")
    ax.axvline(1.0, color="gray", linestyle="--", linewidth=1, label="baseline rainfall")
    # Anchored at 0, not auto-scaled: an auto-zoomed y-axis on a ~1,600 hg/ha
    # range out of a ~197,000 hg/ha baseline would make a genuinely flat
    # response look like sharp swings - a real chart-design pitfall, not a
    # cosmetic choice, given the whole point of this chart is to show flatness.
    ax.set_ylim(0, sensitivity["predicted_yield_hg_ha"].max() * 1.1)
    ax.set_xlabel("Rainfall multiplier (1.0 = actual historical value)")
    ax.set_ylabel("Predicted yield (hg/ha)")
    ax.set_title(f"What-if sensitivity: {area}/{crop}/{year} predicted yield vs. rainfall\n(flat curve = model barely uses rainfall - see D13.1)", fontsize=10)
    ax.legend()
    fig.tight_layout()
    fig.savefig(figures_dir / "12_whatif_rainfall_sensitivity.png", dpi=120)
    plt.close(fig)
    print(f"\nSaved sensitivity chart to {figures_dir / '12_whatif_rainfall_sensitivity.png'}")
