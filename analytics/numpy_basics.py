"""Phase 2 - NumPy fundamentals applied to the ingested yield data.

Concept: a Python list stores boxed Python objects and loops element-by-element
in the interpreter. A NumPy array stores one contiguous block of raw typed
memory and pushes the loop down into compiled C - "vectorization". Same
math, much faster once you're processing more than a handful of numbers,
which real agricultural datasets always are (56k+ yield records here).
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import numpy as np


def load_yield_values(path: Path, crop: str) -> np.ndarray:
    """Read yield.csv (stdlib csv, as in Phase 1) and return one crop's
    Value column as a 1-D NumPy array."""
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        values = [float(row["Value"]) for row in reader if row["Item"] == crop]
    return np.array(values)


def pure_python_hg_to_kg(values: list[float]) -> list[float]:
    """hg/ha -> kg/ha (divide by 10) via a plain Python loop."""
    return [v / 10 for v in values]


def numpy_hg_to_kg(values: np.ndarray) -> np.ndarray:
    """Same conversion, vectorized - one array-wide operation, no explicit loop."""
    return values / 10


def summarize(values: np.ndarray) -> dict[str, float]:
    """Basic vectorized math/reductions - mean, std, min, max, no explicit loop."""
    return {
        "count": values.size,
        "mean": float(values.mean()),
        "std": float(values.std()),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def z_scores(values: np.ndarray) -> np.ndarray:
    """Standardize values: (x - mean) / std. Element-wise broadcasting -
    a scalar mean/std is applied to every element without a loop."""
    return (values - values.mean()) / values.std()


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    yield_path = project_root / "data" / "raw" / "yield.csv"
    crop = "Maize"

    values = load_yield_values(yield_path, crop)

    print(f"Loaded {values.size} {crop} yield values")
    print(f"shape: {values.shape}, ndim: {values.ndim}, dtype: {values.dtype}")

    print(f"\nFirst 5 values (indexing/slicing): {values[:5]}")
    print(f"Every 1000th value: {values[::1000]}")

    print("\nSummary stats (vectorized reductions):")
    for k, v in summarize(values).items():
        print(f"  {k}: {v:.2f}" if isinstance(v, float) else f"  {k}: {v}")

    z = z_scores(values)
    print(f"\nZ-scores (first 5): {z[:5]}")
    print(f"Records more than 3 std above mean (outlier candidates): {(z > 3).sum()}")

    # Vectorization speed comparison
    values_list = values.tolist()

    start = time.perf_counter()
    for _ in range(200):
        pure_python_hg_to_kg(values_list)
    python_time = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(200):
        numpy_hg_to_kg(values)
    numpy_time = time.perf_counter() - start

    print(f"\nhg/ha -> kg/ha, 200 runs over {values.size} values:")
    print(f"  pure Python loop: {python_time:.4f}s")
    print(f"  NumPy vectorized: {numpy_time:.4f}s")
    print(f"  speedup: {python_time / numpy_time:.1f}x")
