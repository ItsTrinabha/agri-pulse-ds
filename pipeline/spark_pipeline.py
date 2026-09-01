"""Phase 16 - PySpark: the same Phase 3 transformation (clean + merge the
four raw sources) reimplemented in Spark DataFrames, run in local mode.

Concept, stated up front because it governs the entire module's framing:
this dataset (tens of thousands of rows, low hundreds of MB across all
four raw files) does NOT need Spark. It comfortably fits in memory on a
single laptop, which is exactly why the Phase 3 pandas pipeline exists and
remains the "real" one this project runs day to day. This module exists to
LEARN Spark - architecture, lazy evaluation, DataFrame transformations vs.
actions, Spark SQL - by porting a already-understood pandas job, and to
honestly measure whether Spark helps at this scale (spoiler, per D16.1:
no - the JVM startup and query-planning overhead alone costs more than
this whole job's actual computation time). Spec section 9's own rule:
"do not use Spark everywhere unnecessarily." This is the demonstration of
knowing that, not a contradiction of it.

Spark concepts demonstrated:
  - SparkSession                  : the entry point (local[*] = driver AND
                                     executors on this one machine, no
                                     cluster - the distributed-computing
                                     model still applies, just with 1 node)
  - DataFrame transformations     : select, filter, withColumn, join,
                                     groupBy/agg - each of these is LAZY,
                                     building a query plan, not running yet
  - actions                       : count(), collect(), write - THESE
                                     trigger actual execution; a printed
                                     "row count" line after a transform-only
                                     chain would be free until an action
                                     forces it, made visible via timing
  - Spark SQL                     : the same join expressed as a SQL string
                                     against a registered temp view, to show
                                     DataFrame API and SQL are two syntaxes
                                     for the same underlying execution plan

To run on Windows (see docs/decisions.md D16.2 for why): set JAVA_HOME to
a real JRE/JDK home (one that has a bin\java.exe - NOT an Oracle "PATH
helper" stub folder) and SPARK_HOME to this pyspark install's own
directory, using 8.3 short paths if either contains a space or
parentheses, e.g.:
    set JAVA_HOME=C:\Program Files\Java\jre1.8.0_491
    set SPARK_HOME=C:\Users\TRINAB~1\...\venv\Lib\SITE-P~1\pyspark
    set SPARK_LOCAL_IP=127.0.0.1
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from pyspark.sql import SparkSession, functions as F


RAINFALL_MISSING_SENTINEL = ".."


def build_spark_session() -> SparkSession:
    return (
        SparkSession.builder
        .appName("AgriPulse-Phase16")
        .master("local[*]")  # all cores of THIS machine act as the executors - no real cluster
        .getOrCreate()
    )


def run_spark_transform(spark: SparkSession, raw_dir: Path) -> "pyspark.sql.DataFrame":
    yield_df = spark.read.csv(str(raw_dir / "yield.csv"), header=True, inferSchema=True)
    pesticides_df = spark.read.csv(str(raw_dir / "pesticides.csv"), header=True, inferSchema=True)
    rainfall_df = spark.read.csv(str(raw_dir / "rainfall.csv"), header=True, inferSchema=True)
    temp_df = spark.read.csv(str(raw_dir / "temp.csv"), header=True, inferSchema=True)

    # --- transformations (lazy - nothing executes yet) ---
    yield_clean = (
        yield_df
        .select(
            F.col("Area").alias("area"),
            F.col("Item").alias("crop"),
            F.col("Year").alias("year"),
            F.col("Value").cast("long").alias("yield_hg_ha"),
        )
    )

    pesticides_clean = (
        pesticides_df
        .select(F.col("Area").alias("area"), F.col("Year").alias("year"), F.col("Value").cast("double").alias("pesticides_tonnes"))
    )

    rainfall_clean = (
        rainfall_df
        .select(
            F.trim(F.col(" Area")).alias("area"),
            F.col("Year").alias("year"),
            F.when(F.col("average_rain_fall_mm_per_year") == RAINFALL_MISSING_SENTINEL, None)
             .otherwise(F.col("average_rain_fall_mm_per_year").cast("double"))
             .alias("rainfall_mm"),
        )
    )

    # temp.csv is sub-annual (Phase 3's D3.3 finding) - aggregate to one
    # row per (area, year) via groupBy/agg BEFORE joining, exactly like
    # the pandas version, for the same reason (avoid a join fan-out).
    temp_clean = (
        temp_df
        .select(F.col("country").alias("area"), F.col("year").alias("year"), F.col("avg_temp").cast("double").alias("avg_temp_c"))
        .groupBy("area", "year")
        .agg(F.avg("avg_temp_c").alias("avg_temp_c"))
    )

    curated = (
        yield_clean
        .join(pesticides_clean, on=["area", "year"], how="left")
        .join(rainfall_clean, on=["area", "year"], how="left")
        .join(temp_clean, on=["area", "year"], how="left")
    )

    return curated


def run_spark_sql_equivalent(spark: SparkSession, raw_dir: Path) -> "pyspark.sql.DataFrame":
    """The same join, expressed as Spark SQL against registered temp views
    - demonstrates that the DataFrame API and SQL compile to the same
    underlying (Catalyst-optimized) execution plan, not two different
    engines."""
    spark.read.csv(str(raw_dir / "yield.csv"), header=True, inferSchema=True).createOrReplaceTempView("yield_raw")
    spark.read.csv(str(raw_dir / "pesticides.csv"), header=True, inferSchema=True).createOrReplaceTempView("pesticides_raw")

    return spark.sql(
        """
        SELECT y.Area AS area, y.Item AS crop, y.Year AS year,
               CAST(y.Value AS LONG) AS yield_hg_ha,
               CAST(p.Value AS DOUBLE) AS pesticides_tonnes
        FROM yield_raw y
        LEFT JOIN pesticides_raw p ON y.Area = p.Area AND y.Year = p.Year
        """
    )


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    raw_dir = project_root / "data" / "raw"
    processed_dir = project_root / "data" / "processed"

    print("Starting Spark session (local[*] - this machine's cores act as the executors)...")
    t0 = time.perf_counter()
    spark = build_spark_session()
    spark.sparkContext.setLogLevel("ERROR")  # Spark's default INFO logging is very noisy for a job this small
    startup_time = time.perf_counter() - t0
    print(f"Spark session startup: {startup_time:.2f}s (this alone often exceeds the whole pandas job's runtime - see D16.1)")

    print(f"\nDefault shuffle partitions: {spark.conf.get('spark.sql.shuffle.partitions')} "
          "(each partition is a unit of parallel work - 200 by default, wildly oversized for ~57k rows on 1 machine)")

    t0 = time.perf_counter()
    curated = run_spark_transform(spark, raw_dir)
    build_time = time.perf_counter() - t0
    print(f"\nBuilt the transformation plan in {build_time:.4f}s - this is suspiciously fast because NOTHING has executed yet (lazy evaluation).")

    t0 = time.perf_counter()
    row_count = curated.count()  # <- the first ACTION: this is what actually triggers execution
    count_time = time.perf_counter() - t0
    print(f"curated.count() [an ACTION, triggers real execution]: {row_count} rows in {count_time:.2f}s")

    print(f"\nPartitions after the joins: {curated.rdd.getNumPartitions()} (Spark shuffled the data across partitions for each join/groupBy)")

    print("\nSample rows (curated.show() - another action):")
    curated.show(5, truncate=False)

    t0 = time.perf_counter()
    out_path = processed_dir / "spark_curated_dataset.csv"
    try:
        # Spark's native writer goes through Hadoop's LocalFileSystem,
        # which on Windows requires winutils.exe (a small native helper
        # binary with no Spark-logic role) just to set file permissions -
        # a well-known Windows-only Spark quirk, irrelevant on the Linux
        # clusters (Databricks, EMR, on-prem) this would actually run on
        # in production. Rather than install more Windows-only plumbing
        # for a local demo, fall back to bringing the (small, ~57k-row)
        # result back to the driver and writing it with pandas - this
        # collect-to-driver pattern is itself a real, common Spark
        # practice for final results that are known to be small.
        curated.coalesce(1).write.mode("overwrite").option("header", True).csv(str(out_path))
        write_time = time.perf_counter() - t0
        print(f"Wrote output (a Spark action) to {out_path} in {write_time:.2f}s")
    except Exception as exc:
        print(f"Spark's native CSV writer failed (expected on Windows without winutils.exe): {type(exc).__name__}")
        print("Falling back to collecting the result to the driver and writing with pandas (see D16.2):")
        # Not curated.toPandas() - PySpark 3.5.x's toPandas() calls a
        # version-check helper (require_minimum_pandas_version) that still
        # imports distutils, which Python 3.12 removed from the stdlib -
        # a second, unrelated environment mismatch. collect() is a plain
        # Spark action (no distutils dependency) that pulls the rows to
        # the driver as plain Python Row objects; building the pandas
        # DataFrame ourselves from there sidesteps the broken helper.
        import pandas as pd
        if out_path.is_dir():  # Spark's failed writer can leave a partial dir at this path
            shutil.rmtree(out_path)
        rows = curated.collect()
        pd.DataFrame([r.asDict() for r in rows]).to_csv(out_path, index=False)
        write_time = time.perf_counter() - t0
        print(f"Wrote output via collect() + pandas to {out_path} in {write_time:.2f}s")

    print("\n=== Spark SQL equivalent (same join, SQL syntax) ===")
    sql_result = run_spark_sql_equivalent(spark, raw_dir)
    sql_result.show(5, truncate=False)

    total_spark_time = startup_time + build_time + count_time + write_time
    print(f"\n=== Total Spark wall time (startup + transform + count + write): {total_spark_time:.2f}s ===")
    print("Compare to pipeline/transform.py's pandas equivalent: see D16.1 for the measured comparison.")

    spark.stop()
