"""Phase 17 - Pipeline Monitoring: wrap the orchestrated pipeline
(pipeline.pipeline.run_pipeline) with run tracking - a unique run ID,
start/end time, duration, per-stage record counts, quality score, status,
and (on failure) an error message - persisted so a failed run can be
diagnosed after the fact, not just watched live in a terminal.

Design note: this writes to its OWN sqlite file (data/processed/
monitoring.db), never to agri_pulse.db. agri_pulse.db is deliberately
rebuilt from scratch on every pipeline run (D4.1 - it's a derived,
reproducible artifact); monitoring history is the opposite - it must
SURVIVE every run, that's the entire point of "can I see what happened
across past runs." Putting both in one file that gets wiped each run
would silently delete monitoring history on every successful run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import traceback
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from pipeline.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id                 TEXT PRIMARY KEY,
    started_at              TEXT NOT NULL,
    ended_at                 TEXT,
    duration_sec              REAL,
    status                    TEXT NOT NULL,   -- SUCCESS | FAILED
    error_message             TEXT,
    records_received          INTEGER,
    records_accepted          INTEGER,
    records_rejected          INTEGER,
    overall_quality_score_pct REAL,
    curated_rows               INTEGER,
    stage_detail_json          TEXT NOT NULL
);
"""


@dataclass
class PipelineRunRecord:
    run_id: str
    started_at: str
    ended_at: str | None
    duration_sec: float | None
    status: str
    error_message: str | None
    records_received: int | None
    records_accepted: int | None
    records_rejected: int | None
    overall_quality_score_pct: float | None
    curated_rows: int | None
    stage_detail_json: str


def _monitoring_db(monitoring_db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(monitoring_db_path)
    conn.execute(SCHEMA)
    return conn


def _summarize_stages(stages) -> dict:
    ingestion = next((s for s in stages if s.stage == "ingestion"), None)
    quality = next((s for s in stages if s.stage == "data_quality"), None)
    transform = next((s for s in stages if s.stage == "transform"), None)

    records_received = sum(ingestion.detail["records"].values()) if ingestion else None
    records_accepted = sum(v["accepted"] for v in quality.detail.values()) if quality else None
    records_rejected = sum(v["rejected"] for v in quality.detail.values()) if quality else None
    overall_quality = (
        round(100 * records_accepted / records_received, 2)
        if quality and records_received else None
    )
    curated_rows = transform.detail["curated_rows"] if transform else None

    return {
        "records_received": records_received,
        "records_accepted": records_accepted,
        "records_rejected": records_rejected,
        "overall_quality_score_pct": overall_quality,
        "curated_rows": curated_rows,
    }


def run_monitored_pipeline(project_root: Path, monitoring_db_path: Path) -> PipelineRunRecord:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = datetime.now(timezone.utc)

    conn = _monitoring_db(monitoring_db_path)
    try:
        stages = run_pipeline(project_root)
        ended_at = datetime.now(timezone.utc)
        summary = _summarize_stages(stages)

        record = PipelineRunRecord(
            run_id=run_id,
            started_at=started_at,
            ended_at=ended_at.isoformat(),
            duration_sec=(ended_at - t0).total_seconds(),
            status="SUCCESS",
            error_message=None,
            stage_detail_json=json.dumps([asdict(s) for s in stages]),
            **summary,
        )
    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        record = PipelineRunRecord(
            run_id=run_id,
            started_at=started_at,
            ended_at=ended_at.isoformat(),
            duration_sec=(ended_at - t0).total_seconds(),
            status="FAILED",
            error_message=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            records_received=None, records_accepted=None, records_rejected=None,
            overall_quality_score_pct=None, curated_rows=None,
            stage_detail_json="[]",
        )
        _persist(conn, record)
        conn.close()
        logger.error("Pipeline run %s FAILED: %s", run_id, exc)
        raise  # monitoring logs the failure but does not swallow it - callers still see it

    _persist(conn, record)
    conn.close()
    logger.info("Pipeline run %s SUCCESS in %.2fs", run_id, record.duration_sec)
    return record


def _persist(conn: sqlite3.Connection, record: PipelineRunRecord) -> None:
    conn.execute(
        """INSERT INTO pipeline_run
           (run_id, started_at, ended_at, duration_sec, status, error_message,
            records_received, records_accepted, records_rejected,
            overall_quality_score_pct, curated_rows, stage_detail_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record.run_id, record.started_at, record.ended_at, record.duration_sec,
            record.status, record.error_message,
            record.records_received, record.records_accepted, record.records_rejected,
            record.overall_quality_score_pct, record.curated_rows, record.stage_detail_json,
        ),
    )
    conn.commit()


def get_run_history(monitoring_db_path: Path, limit: int = 10) -> list[sqlite3.Row]:
    conn = _monitoring_db(monitoring_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM pipeline_run ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def diagnose_last_failure(monitoring_db_path: Path) -> sqlite3.Row | None:
    conn = _monitoring_db(monitoring_db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM pipeline_run WHERE status = 'FAILED' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    monitoring_db_path = project_root / "data" / "processed" / "monitoring.db"

    print("=== Run 1: normal pipeline run ===")
    record = run_monitored_pipeline(project_root, monitoring_db_path)
    print(f"run_id={record.run_id}  status={record.status}  duration={record.duration_sec:.2f}s")
    print(f"  received={record.records_received}  accepted={record.records_accepted}  "
          f"rejected={record.records_rejected}  quality={record.overall_quality_score_pct}%  "
          f"curated_rows={record.curated_rows}")

    print("\n=== Run 2: DELIBERATELY induced failure (temp.csv source removed) ===")
    # Both external/ and raw/ copies must go: ingestion runs FIRST in the
    # pipeline and would otherwise just re-copy external/temp.csv back
    # into raw/, silently undoing the induced failure before the quality
    # stage (which is what actually errors on a missing raw file) ever ran.
    temp_external = project_root / "data" / "external" / "temp.csv"
    temp_external_backup = project_root / "data" / "external" / "temp.csv.bak"
    temp_raw = project_root / "data" / "raw" / "temp.csv"
    temp_raw_backup = project_root / "data" / "raw" / "temp.csv.bak"
    temp_external.rename(temp_external_backup)
    temp_raw.rename(temp_raw_backup)
    try:
        run_monitored_pipeline(project_root, monitoring_db_path)
    except Exception as exc:
        print(f"Caught expected failure: {type(exc).__name__}: {exc}")
    finally:
        temp_external_backup.rename(temp_external)
        temp_raw_backup.rename(temp_raw)  # restore - this was a deliberate demo, not a real defect

    print("\n=== Diagnosing the last failure (this is what 'diagnose a failed pipeline' looks like) ===")
    failure = diagnose_last_failure(monitoring_db_path)
    if failure:
        print(f"run_id={failure['run_id']}  started_at={failure['started_at']}  status={failure['status']}")
        print(f"error_message (first 300 chars):\n{failure['error_message'][:300]}")

    print("\n=== Run history (most recent first) ===")
    for row in get_run_history(monitoring_db_path, limit=5):
        print(
            f"  {row['started_at']}  {row['status']:8s}  "
            f"duration={row['duration_sec']:.2f}s  "
            f"quality={row['overall_quality_score_pct']}%  "
            f"curated_rows={row['curated_rows']}"
        )
