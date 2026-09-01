"""Phase 7 - Exploratory Data Analysis: answer the five business questions
the roadmap sets for this phase, with a chart per question and a written
report tying the numbers to a plain-language conclusion.

Concept: EDA != "make some plots". A plot earns its place only if it
answers a specific question - each function below is named after the
question it answers, not the chart type it draws.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless: writes files, doesn't try to open a window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def which_crops_perform_best(df: pd.DataFrame, figures_dir: Path) -> pd.Series:
    by_crop = df.groupby("crop")["yield_hg_ha"].mean().sort_values(ascending=False)

    fig, ax = plt.subplots(figsize=(8, 5))
    by_crop.plot(kind="barh", ax=ax, color="#4c8c4a")
    ax.set_xlabel("Average yield (hg/ha)")
    ax.set_title("Average yield by crop (all regions/years)")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(figures_dir / "01_yield_by_crop.png", dpi=120)
    plt.close(fig)
    return by_crop


def which_regions_perform_best(df: pd.DataFrame, figures_dir: Path, top_n: int = 15) -> pd.Series:
    """Fair cross-crop regional ranking: average yield alone favors regions
    that happen to grow high-yield crops (e.g. potatoes over soybeans), so
    this standardizes within each crop first (z-score), then averages the
    z-scores per region - "how far above/below crop-typical is this
    region, on average, across every crop it grows"."""
    grouped = df.groupby("crop")["yield_hg_ha"]
    z = (df["yield_hg_ha"] - grouped.transform("mean")) / grouped.transform("std")
    region_score = z.groupby(df["area"]).mean().sort_values(ascending=False)
    top = region_score.head(top_n)

    fig, ax = plt.subplots(figsize=(8, 6))
    top.plot(kind="barh", ax=ax, color="#3a6ea5")
    ax.set_xlabel("Mean cross-crop yield z-score (0 = crop-typical)")
    ax.set_title(f"Top {top_n} regions by cross-crop standardized yield")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(figures_dir / "02_top_regions.png", dpi=120)
    plt.close(fig)
    return region_score


def how_does_rainfall_relate_to_yield(df: pd.DataFrame, figures_dir: Path) -> pd.Series:
    fig, ax = plt.subplots(figsize=(7, 6))
    subset = df.dropna(subset=["rainfall_mm", "yield_hg_ha"])
    subset = subset[subset["crop"] == "Maize"]
    ax.scatter(subset["rainfall_mm"], subset["yield_hg_ha"], alpha=0.25, s=12, color="#2f6f4f")
    if len(subset) > 1:
        coeffs = np.polyfit(subset["rainfall_mm"], subset["yield_hg_ha"], 1)
        x_line = np.linspace(subset["rainfall_mm"].min(), subset["rainfall_mm"].max(), 100)
        ax.plot(x_line, np.polyval(coeffs, x_line), color="#c0392b", linewidth=2, label="linear trend")
        ax.legend()
    ax.set_xlabel("Rainfall (mm/year)")
    ax.set_ylabel("Maize yield (hg/ha)")
    ax.set_title("Maize yield vs. rainfall (each point = one region-year)")
    fig.tight_layout()
    fig.savefig(figures_dir / "03_rainfall_vs_yield.png", dpi=120)
    plt.close(fig)

    correlations = {}
    for crop in df["crop"].unique():
        crop_df = df[df["crop"] == crop].dropna(subset=["rainfall_mm", "yield_hg_ha"])
        if len(crop_df) > 30:
            correlations[crop] = crop_df["rainfall_mm"].corr(crop_df["yield_hg_ha"])
    corr_series = pd.Series(correlations).sort_values()

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = ["#c0392b" if v < 0 else "#2f6f4f" for v in corr_series]
    corr_series.plot(kind="barh", ax=ax, color=colors)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Pearson correlation (rainfall vs yield)")
    ax.set_title("Rainfall-yield correlation by crop")
    fig.tight_layout()
    fig.savefig(figures_dir / "04_rainfall_correlation_by_crop.png", dpi=120)
    plt.close(fig)

    return corr_series


def where_are_the_outliers(df: pd.DataFrame, figures_dir: Path) -> pd.DataFrame:
    crops = df["crop"].unique()
    data = [df.loc[df["crop"] == c, "yield_hg_ha"].values for c in crops]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.boxplot(data, tick_labels=crops, orientation="horizontal", showfliers=True, flierprops={"markersize": 2, "alpha": 0.4})
    ax.set_xlabel("Yield (hg/ha)")
    ax.set_title("Yield distribution and outliers by crop (IQR boxplot)")
    fig.tight_layout()
    fig.savefig(figures_dir / "05_outliers_by_crop.png", dpi=120)
    plt.close(fig)

    rows = []
    for crop in crops:
        values = df.loc[df["crop"] == crop, "yield_hg_ha"]
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = values[(values < lower) | (values > upper)]
        rows.append({"crop": crop, "outlier_count": len(outliers), "outlier_pct": round(100 * len(outliers) / len(values), 2)})
    return pd.DataFrame(rows).sort_values("outlier_pct", ascending=False)


def what_data_problems_exist(df: pd.DataFrame, figures_dir: Path) -> pd.DataFrame:
    """Coverage of each joined source by decade - shows the mismatched
    year ranges (D_ decisions in Phase 3) as a concrete, visual problem
    rather than an abstract caveat."""
    decade = (df["year"] // 10) * 10
    coverage = df.groupby(decade).agg(
        rainfall_coverage_pct=("rainfall_mm", lambda s: 100 * s.notna().mean()),
        temp_coverage_pct=("avg_temp_c", lambda s: 100 * s.notna().mean()),
        pesticides_coverage_pct=("pesticides_tonnes", lambda s: 100 * s.notna().mean()),
    )
    coverage.index.name = "decade"

    fig, ax = plt.subplots(figsize=(9, 5))
    coverage.plot(kind="line", marker="o", ax=ax)
    ax.set_ylabel("% of yield rows with a matched value")
    ax.set_xlabel("Decade")
    ax.set_title("Data coverage by decade - why early-year models will have fewer usable features")
    ax.set_ylim(0, 105)
    fig.tight_layout()
    fig.savefig(figures_dir / "06_coverage_by_decade.png", dpi=120)
    plt.close(fig)
    return coverage


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")
    figures_dir = project_root / "notebooks" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    print("=== Q1: Which crops perform best? ===")
    print(which_crops_perform_best(df, figures_dir))

    print("\n=== Q2: Which regions perform best (cross-crop standardized)? ===")
    print(which_regions_perform_best(df, figures_dir, top_n=15))

    print("\n=== Q3: How does rainfall relate to yield? ===")
    print(how_does_rainfall_relate_to_yield(df, figures_dir))

    print("\n=== Q4: Where are the outliers? ===")
    print(where_are_the_outliers(df, figures_dir))

    print("\n=== Q5: What data problems exist? ===")
    print(what_data_problems_exist(df, figures_dir))

    print(f"\nSaved 6 charts to {figures_dir}")
