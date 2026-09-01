"""Phase 5 - the Data Quality Engine: run schema + rule checks on a raw
source, split it into accepted vs. quarantined rows (with reasons), and
produce a quality score.

Output per spec section 4.2: valid record count, rejected record count,
reason for rejection, quality score, validation status. Nothing is
silently deleted - rejected rows are written to data/quarantine/.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from quality.schema_checks import SCHEMAS, validate_schema
from quality.validation_rules import RULES_BY_SOURCE

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RAINFALL_MISSING_SENTINEL = ".."


def _preprocess_rainfall(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce the ".." sentinel to NaN so numeric rules can run - see
    docs/data_dictionary.md. Kept local to quality_report.py rather than
    validation_rules.py, since it's data prep, not a validity check."""
    df = df.copy()
    df.columns = df.columns.str.strip()
    df["rainfall_numeric"] = pd.to_numeric(
        df["average_rain_fall_mm_per_year"].replace(RAINFALL_MISSING_SENTINEL, pd.NA),
        errors="coerce",
    )
    return df


PREPROCESS_BY_SOURCE = {"rainfall": _preprocess_rainfall}


@dataclass
class QualityReport:
    source_name: str
    schema_passed: bool
    schema_missing_columns: list[str]
    total_records: int
    accepted_records: int
    rejected_records: int
    quality_score_pct: float
    rejection_reason_counts: dict[str, int] = field(default_factory=dict)
    null_counts: dict[str, int] = field(default_factory=dict)
    validation_status: str = "UNKNOWN"


def run_quality_checks(df: pd.DataFrame, source_name: str, quarantine_dir: Path) -> tuple[QualityReport, pd.DataFrame]:
    """Returns (report, accepted_df) - accepted_df is handed to
    pipeline.py (Phase 15) so downstream transform runs on quality-
    filtered data, not just the untouched raw file (closing D6.1's gap)."""
    schema = SCHEMAS[source_name]
    schema_result = validate_schema(df, schema)

    if not schema_result.passed:
        # A missing required column is a file-level failure - nothing in
        # this file can be trusted row-by-row, so it's all rejected.
        report = QualityReport(
            source_name=source_name,
            schema_passed=False,
            schema_missing_columns=schema_result.missing_columns,
            total_records=len(df),
            accepted_records=0,
            rejected_records=len(df),
            quality_score_pct=0.0,
            rejection_reason_counts={"schema_validation_failed": len(df)},
            validation_status="FAILED",
        )
        df.assign(reject_reason="schema_validation_failed").to_csv(
            quarantine_dir / f"{source_name}_rejected.csv", index=False
        )
        return report, df.iloc[0:0]

    working = PREPROCESS_BY_SOURCE.get(source_name, lambda d: d)(df).reset_index(drop=True)

    reasons_per_row: list[list[str]] = [[] for _ in range(len(working))]
    for rule in RULES_BY_SOURCE[source_name]:
        invalid_mask = rule.check_fn(working).fillna(False).to_numpy()
        for pos in invalid_mask.nonzero()[0]:
            reasons_per_row[pos].append(rule.reason)

    reject_reason = pd.Series([";".join(r) if r else "" for r in reasons_per_row])
    is_rejected = reject_reason != ""

    accepted = df[~is_rejected.values]
    rejected = df[is_rejected.values].copy()
    rejected["reject_reason"] = reject_reason[is_rejected.values].values

    quarantine_dir.mkdir(parents=True, exist_ok=True)
    rejected.to_csv(quarantine_dir / f"{source_name}_rejected.csv", index=False)

    reason_counts: dict[str, int] = {}
    for reasons in reasons_per_row:
        for r in reasons:
            reason_counts[r] = reason_counts.get(r, 0) + 1

    total = len(df)
    accepted_count = len(accepted)
    quality_score = round(100 * accepted_count / total, 2) if total else 0.0

    report = QualityReport(
        source_name=source_name,
        schema_passed=True,
        schema_missing_columns=[],
        total_records=total,
        accepted_records=accepted_count,
        rejected_records=total - accepted_count,
        quality_score_pct=quality_score,
        rejection_reason_counts=reason_counts,
        null_counts=df.isnull().sum().to_dict(),
        validation_status="PASSED" if quality_score >= 95 else "PASSED_WITH_WARNINGS" if quality_score >= 80 else "FAILED",
    )

    logger.info(
        "%s: %d/%d accepted (%.2f%% quality score), status=%s",
        source_name, accepted_count, total, quality_score, report.validation_status,
    )
    return report, accepted


def run_all(raw_dir: Path, quarantine_dir: Path) -> tuple[dict[str, QualityReport], dict[str, pd.DataFrame]]:
    reports, accepted_frames = {}, {}
    for source_name in SCHEMAS:
        df = pd.read_csv(raw_dir / f"{source_name}.csv")
        reports[source_name], accepted_frames[source_name] = run_quality_checks(df, source_name, quarantine_dir)
    return reports, accepted_frames


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    raw_dir = project_root / "data" / "raw"
    quarantine_dir = project_root / "data" / "quarantine"

    reports, _accepted_frames = run_all(raw_dir, quarantine_dir)

    overall_total = sum(r.total_records for r in reports.values())
    overall_accepted = sum(r.accepted_records for r in reports.values())
    overall_score = round(100 * overall_accepted / overall_total, 2) if overall_total else 0.0

    summary = {
        "per_source": {name: asdict(r) for name, r in reports.items()},
        "overall_quality_score_pct": overall_score,
        "overall_total_records": overall_total,
        "overall_accepted_records": overall_accepted,
        "overall_rejected_records": overall_total - overall_accepted,
    }

    with (quarantine_dir / "_quality_report.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n=== Overall quality score: {overall_score}% ({overall_accepted}/{overall_total} accepted) ===\n")
    for name, r in reports.items():
        print(f"{name}: {r.validation_status} - {r.accepted_records}/{r.total_records} accepted ({r.quality_score_pct}%)")
        if r.rejection_reason_counts:
            for reason, count in r.rejection_reason_counts.items():
                print(f"    {reason}: {count}")
