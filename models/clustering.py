"""Phase 11 - Clustering: K-Means over growing CONDITIONS (rainfall,
temperature, pesticide use) at (region, year) grain, to discover natural
groupings of farming environments - independent of yield.

Design choice: yield is deliberately NOT a clustering feature, even though
spec section 5 lists it as a candidate. Clustering on conditions and then
reporting each cluster's mean yield afterward keeps the two questions
separate: "what kinds of growing environments exist" (unsupervised,
condition-based) vs. "how well did each kind of environment perform"
(a business interpretation layered on top, not baked into the grouping).

Concept: K-Means needs (1) every feature on a comparable scale, since it
minimizes Euclidean distance and a feature measured in the thousands would
dominate one measured in single digits regardless of real importance, and
(2) a chosen K - there's no single correct answer, so this uses both the
elbow method (inertia) and silhouette score rather than picking arbitrarily.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

FEATURES = ["rainfall_mm", "avg_temp_c", "pesticides_tonnes"]


def build_region_year_conditions(df: pd.DataFrame) -> pd.DataFrame:
    """(region, year) grain, complete cases only - K-Means can't handle
    NaN, and imputing conditions data specifically to make clustering work
    would manufacture the very groupings we're trying to discover."""
    region_year = df.drop_duplicates(subset=["area", "year"])[["area", "year"] + FEATURES]
    complete = region_year.dropna(subset=FEATURES)
    return complete


def choose_k(X_scaled: np.ndarray, k_range: range, figures_dir: Path) -> pd.DataFrame:
    rows = []
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X_scaled)
        sil = silhouette_score(X_scaled, km.labels_) if k > 1 else np.nan
        rows.append({"k": k, "inertia": km.inertia_, "silhouette": sil})
    result = pd.DataFrame(rows)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    ax1.plot(result["k"], result["inertia"], marker="o")
    ax1.set_xlabel("K")
    ax1.set_ylabel("Inertia (within-cluster sum of squares)")
    ax1.set_title("Elbow method")

    ax2.plot(result["k"], result["silhouette"], marker="o", color="#2f6f4f")
    ax2.set_xlabel("K")
    ax2.set_ylabel("Silhouette score")
    ax2.set_title("Silhouette score by K")

    fig.tight_layout()
    fig.savefig(figures_dir / "08_kmeans_choosing_k.png", dpi=120)
    plt.close(fig)
    return result


def interpret_clusters(conditions: pd.DataFrame, labels: np.ndarray, curated: pd.DataFrame) -> pd.DataFrame:
    conditions = conditions.copy()
    conditions["cluster"] = labels

    profile = conditions.groupby("cluster")[FEATURES].mean()
    profile["n_region_years"] = conditions.groupby("cluster").size()

    # Business interpretation layer: mean yield (all crops, mean of each
    # crop's own z-score per D7.3/Phase 7 Q2 approach) for region-years in
    # each cluster - joined back from curated_dataset, not used to form
    # the clusters themselves.
    crop_z = (curated["yield_hg_ha"] - curated.groupby("crop")["yield_hg_ha"].transform("mean")) / curated.groupby("crop")["yield_hg_ha"].transform("std")
    yield_lookup = crop_z.groupby([curated["area"], curated["year"]]).mean()
    conditions["yield_zscore"] = conditions.apply(lambda r: yield_lookup.get((r["area"], r["year"]), np.nan), axis=1)
    profile["mean_yield_zscore"] = conditions.groupby("cluster")["yield_zscore"].mean()

    return profile.sort_values("avg_temp_c")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    df = pd.read_csv(project_root / "data" / "processed" / "curated_dataset.csv")
    figures_dir = project_root / "notebooks" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    conditions = build_region_year_conditions(df)
    print(f"Region-year rows with complete rainfall/temp/pesticide data: {len(conditions)}")

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(conditions[FEATURES])

    k_search = choose_k(X_scaled, range(2, 9), figures_dir)
    print("\nK search (elbow + silhouette):")
    print(k_search.to_string(index=False))

    # K=4 chosen: inertia's marginal drop flattens noticeably after 4
    # (elbow), and silhouette is at or near its local peak there without
    # collapsing to trivially small clusters at higher K - see D11.1.
    K = 4
    kmeans = KMeans(n_clusters=K, random_state=42, n_init=10).fit(X_scaled)
    print(f"\nUsing K={K} (see docs/decisions.md D11.1 for the elbow+silhouette reasoning)")

    profile = interpret_clusters(conditions, kmeans.labels_, df)
    print("\n=== Cluster profiles (mean of original-unit features) ===")
    print(profile.to_string())

    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(
        conditions["rainfall_mm"], conditions["avg_temp_c"], c=kmeans.labels_, cmap="viridis", alpha=0.4, s=15
    )
    ax.set_xlabel("Rainfall (mm/year)")
    ax.set_ylabel("Avg temperature (C)")
    ax.set_title(f"K-Means clusters (K={K}) over rainfall/temperature\n(pesticide use is the 3rd, unplotted dimension)", fontsize=10)
    legend = ax.legend(*scatter.legend_elements(), title="Cluster")
    ax.add_artist(legend)
    fig.tight_layout()
    fig.savefig(figures_dir / "09_kmeans_clusters.png", dpi=120)
    plt.close(fig)

    print(f"\nSaved cluster-selection and cluster-scatter figures to {figures_dir}")
