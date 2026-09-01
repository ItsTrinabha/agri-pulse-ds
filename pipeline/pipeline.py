"""Phase 15 - Data Engineering Architecture: the orchestrated pipeline,
running every stage in the order the architecture diagram (docs/
architecture.md) actually specifies:

  DATA SOURCES -> INGESTION -> RAW DATA LAKE -> DATA QUALITY
    -> (QUARANTINE | ACCEPTED) -> TRANSFORMATION/ETL -> CURATED DATA
    -> SQL LOAD

This is what "refactor notebook/script work into pipeline stages" (Phase
15's build task) means concretely: Phases 1/3/5 were each developed and
run independently (a realistic way to build and debug one stage at a
time), which is exactly why nothing enforced that Phase 3's transform
consumed Phase 5's quality-ACCEPTED rows rather than the raw file
directly - a gap flagged back in D6.1. This module is the fix: one
callable, ordered pipeline, with per-stage timing/counts recorded (the
seed of Phase 17's pipeline monitoring).

ETL, not ELT: transformation happens before the data is loaded into the
SQL layer (pipeline/transform.py runs, THEN database/load_db.py runs on
its output) - chosen because the curated dataset is small enough (tens of
thousands of rows) that transforming in Python/pandas before loading is
simpler than loading raw data into SQL and transforming there with SQL
itself (which would be the ELT alternative, more common at data volumes
where the warehouse's compute is the reason to push transformation there).

Batch, not streaming: this is a single scheduled/on-demand run over a
static file-based data source, not a continuous stream - see docs/
architecture.md's Azure mapping for how a streaming source would change
this (Event Hub -> Databricks structured streaming, not this module).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from database.load_db import build_database
from ingestion.csv_ingestion import ingest_all
from pipeline.transform import build_curated_dataset_from_frames
from quality.quality_report import run_all as run_quality_all


@dataclass
class StageResult:
    stage: str
    duration_sec: float
    detail: dict


def run_pipeline(project_root: Path) -> list[StageResult]:
    external_dir = project_root / "data" / "external"
    raw_dir = project_root / "data" / "raw"
    quarantine_dir = project_root / "data" / "quarantine"
    processed_dir = project_root / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    stages: list[StageResult] = []

    # Stage 1: INGESTION (source -> raw data lake)
    t0 = time.perf_counter()
    source_files = ["yield.csv", "pesticides.csv", "rainfall.csv", "temp.csv"]
    ingestion_results = ingest_all(external_dir, raw_dir, source_files)
    stages.append(StageResult(
        "ingestion", time.perf_counter() - t0,
        {"files_ingested": len(ingestion_results), "records": {r.source_name: r.record_count for r in ingestion_results}},
    ))

    # Stage 2: DATA QUALITY (raw -> accepted | quarantine)
    t0 = time.perf_counter()
    quality_reports, accepted_frames = run_quality_all(raw_dir, quarantine_dir)
    stages.append(StageResult(
        "data_quality", time.perf_counter() - t0,
        {name: {"accepted": r.accepted_records, "rejected": r.rejected_records, "score_pct": r.quality_score_pct} for name, r in quality_reports.items()},
    ))

    # Stage 3: TRANSFORMATION/ETL (accepted raw -> curated), now correctly
    # consuming QUALITY-ACCEPTED frames, not the untouched raw files -
    # this is the D6.1 gap closed.
    t0 = time.perf_counter()
    curated, transform_report = build_curated_dataset_from_frames(
        accepted_frames["yield"], accepted_frames["pesticides"], accepted_frames["rainfall"], accepted_frames["temp"]
    )
    curated_path = processed_dir / "curated_dataset.csv"
    curated.to_csv(curated_path, index=False)
    with (processed_dir / "_transform_report.json").open("w", encoding="utf-8") as f:
        json.dump(transform_report, f, indent=2)
    stages.append(StageResult("transform", time.perf_counter() - t0, {"curated_rows": len(curated), "curated_path": str(curated_path)}))

    # Stage 4: SQL LOAD (curated -> normalized SQLite tables)
    t0 = time.perf_counter()
    db_path = processed_dir / "agri_pulse.db"
    build_database(db_path, curated_path, project_root / "database" / "schema.sql")
    stages.append(StageResult("sql_load", time.perf_counter() - t0, {"db_path": str(db_path)}))

    return stages


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    stages = run_pipeline(project_root)

    print("\n=== Pipeline run summary ===")
    total_duration = sum(s.duration_sec for s in stages)
    for s in stages:
        print(f"  [{s.duration_sec:6.2f}s] {s.stage}: {s.detail}")
    print(f"  Total duration: {total_duration:.2f}s")

    run_log_path = project_root / "data" / "processed" / "_pipeline_run_log.json"
    with run_log_path.open("w", encoding="utf-8") as f:
        json.dump({"stages": [asdict(s) for s in stages], "total_duration_sec": total_duration}, f, indent=2)
    print(f"\nSaved pipeline run log to {run_log_path}")

    curated_rows = next(s.detail["curated_rows"] for s in stages if s.stage == "transform")
    print(
        f"\nBefore this refactor, the curated dataset (and everything built on it in Phases 6-14) "
        f"was built directly from raw data, bypassing the Phase 5 quality filter (D6.1's flagged gap). "
        f"This run's curated dataset has {curated_rows} rows, quality-filtered from the raw sources - "
        f"a small difference from the original 56,717 (9 yield records + any propagated weather/pesticide "
        f"rejections), quantified rather than assumed negligible."
    )
