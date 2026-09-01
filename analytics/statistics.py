"""Phase 6 - Statistics: an agricultural statistical report over the
curated dataset. The point of this phase is interpreting statistics, not
just calculating them - every function below returns numbers, but the
__main__ block prints a plain-language reading of what they mean.

Known scope gap: this runs on data/processed/curated_dataset.csv (Phase 3
output), which does not yet exclude the 9 records the Phase 5 Data Quality
Engine quarantined (0.016% of rows) - full pipeline wiring (quality ->
transform in the correct order) happens in Phase 15. Negligible effect on
these statistics; noted rather than silently ignored.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def yield_distribution(df: pd.DataFrame, crop: str) -> dict[str, float]:
    """Mean, median, variance, std, and percentiles for one crop's yield."""
    values = df.loc[df["crop"] == crop, "yield_hg_ha"]
    return {
        "count": int(values.count()),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "variance": float(values.var()),
        "std": float(values.std()),
        "p10": float(values.quantile(0.10)),
        "p25": float(values.quantile(0.25)),
        "p75": float(values.quantile(0.75)),
        "p90": float(values.quantile(0.90)),
        "skew": float(values.skew()),
    }


def regional_averages(df: pd.DataFrame, crop: str, top_n: int = 10) -> pd.DataFrame:
    """Average yield per region for one crop, plus how many std devs each
    region sits from the global mean for that crop (a standardized way to
    say "high" or "low" that accounts for spread, not just raw ranking)."""
    crop_df = df[df["crop"] == crop]
    global_mean = crop_df["yield_hg_ha"].mean()
    global_std = crop_df["yield_hg_ha"].std()

    by_region = crop_df.groupby("area")["yield_hg_ha"].agg(["mean", "count"])
    by_region["z_vs_global"] = (by_region["mean"] - global_mean) / global_std
    return by_region.sort_values("mean", ascending=False).head(top_n)


def correlation_report(df: pd.DataFrame, crop: str) -> pd.DataFrame:
    """Pearson correlation of yield with rainfall/temperature/pesticide use,
    for rows where all three are available (an incomplete-case correlation -
    see the printed caveat in __main__)."""
    crop_df = df[df["crop"] == crop][["yield_hg_ha", "rainfall_mm", "avg_temp_c", "pesticides_tonnes"]].dropna()
    return crop_df.corr()


def outlier_analysis(df: pd.DataFrame, crop: str) -> dict[str, object]:
    """IQR-based outlier detection: a point is an outlier if it falls
    outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR] - a standard, distribution-free
    rule of thumb (unlike a z-score cutoff, doesn't assume normality)."""
    values = df.loc[df["crop"] == crop, "yield_hg_ha"]
    q1, q3 = values.quantile(0.25), values.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = values[(values < lower) | (values > upper)]
    return {
        "iqr_lower_bound": float(lower),
        "iqr_upper_bound": float(upper),
        "outlier_count": int(outliers.count()),
        "outlier_pct": round(100 * outliers.count() / values.count(), 2),
    }


def confidence_interval_mean(values: pd.Series, confidence: float = 0.95) -> tuple[float, float, float]:
    """95% CI for the sample mean, via the normal approximation
    (justified here since n is in the thousands - CLT applies comfortably;
    for small samples a t-distribution CI would be needed instead)."""
    n = values.count()
    mean = values.mean()
    se = values.std(ddof=1) / np.sqrt(n)
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    return mean, mean - z * se, mean + z * se


def yield_trend_ttest(df: pd.DataFrame, crop: str, split_year: int) -> dict[str, float]:
    """Independent-samples t-test: is mean yield significantly different
    before vs. on-or-after split_year? Tests H0: the two period means are
    equal. A small p-value (< 0.05) means the observed difference is
    unlikely to be due to chance alone - it does NOT by itself say why
    (better varieties, more fertilizer, climate - unknown from this test)."""
    crop_df = df[df["crop"] == crop]
    before = crop_df.loc[crop_df["year"] < split_year, "yield_hg_ha"]
    after = crop_df.loc[crop_df["year"] >= split_year, "yield_hg_ha"]
    t_stat, p_value = stats.ttest_ind(before, after, equal_var=False)
    return {
        "before_mean": float(before.mean()),
        "after_mean": float(after.mean()),
        "before_n": int(before.count()),
        "after_n": int(after.count()),
        "t_statistic": float(t_stat),
        "p_value": float(p_value),
    }


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")
    crop = "Maize"

    print(f"=== Yield distribution: {crop} (hg/ha) ===")
    dist = yield_distribution(df, crop)
    for k, v in dist.items():
        print(f"  {k}: {v:,.2f}" if isinstance(v, float) else f"  {k}: {v}")
    print(
        f"  -> median ({dist['median']:,.0f}) is {'below' if dist['median'] < dist['mean'] else 'above'} "
        f"the mean ({dist['mean']:,.0f}), and skew is {dist['skew']:.2f} (>0 = right-skewed): "
        "a small number of very high-yield region/years pull the mean up above the typical value."
    )

    print(f"\n=== Top 10 regions by average {crop} yield (with z-score vs. global mean) ===")
    print(regional_averages(df, crop))

    print(f"\n=== Correlation of {crop} yield with rainfall / temperature / pesticide use ===")
    corr = correlation_report(df, crop)
    print(corr["yield_hg_ha"])
    n_complete = df[df["crop"] == crop][["rainfall_mm", "avg_temp_c", "pesticides_tonnes"]].dropna().shape[0]
    n_total = (df["crop"] == crop).sum()
    print(
        f"  (n={n_complete}/{n_total} rows with all three values present - correlation only reflects "
        "these, not the full dataset. Correlation measures association, not causation - "
        "e.g. a positive pesticide-yield correlation may partly reflect that wealthier/more "
        "intensive farming systems use more of both, not that pesticide use alone drives yield.)"
    )

    print(f"\n=== Outlier analysis: {crop} yield (IQR method) ===")
    outliers = outlier_analysis(df, crop)
    for k, v in outliers.items():
        print(f"  {k}: {v}")

    mean, lo, hi = confidence_interval_mean(df.loc[df["crop"] == crop, "yield_hg_ha"])
    print(f"\n=== 95% confidence interval for mean {crop} yield ===")
    print(f"  mean={mean:,.1f}, 95% CI=({lo:,.1f}, {hi:,.1f})")
    print("  -> if we resampled this population repeatedly, ~95% of such intervals would contain the true mean.")

    print(f"\n=== Hypothesis test: has mean {crop} yield changed since 1990? ===")
    ttest = yield_trend_ttest(df, crop, split_year=1990)
    for k, v in ttest.items():
        print(f"  {k}: {v:,.4f}" if isinstance(v, float) else f"  {k}: {v}")
    verdict = "statistically significant" if ttest["p_value"] < 0.05 else "not statistically significant"
    print(
        f"  -> mean yield went from {ttest['before_mean']:,.0f} (pre-1990) to {ttest['after_mean']:,.0f} "
        f"(1990+), a {verdict} difference at alpha=0.05 (p={ttest['p_value']:.2e})."
    )
