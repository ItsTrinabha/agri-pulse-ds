"""Phase 1 ingestion: move a source CSV into the raw data lake using only
the Python standard library (csv, pathlib, json) - no pandas yet.

Concept: ingestion is the boundary between "data someone else produced"
(data/external/) and "data our system has taken custody of and recorded
the receipt of" (data/raw/). It should fail loudly on a missing/malformed
source rather than silently producing an empty raw file.
"""

from __future__ import annotations

import csv
import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    source_name: str
    source_path: str
    raw_path: str
    columns: list[str]
    record_count: int
    ingested_at: str


def validate_file_exists(path: Path) -> None:
    """Raise a clear error if the source file is missing.

    Fails loudly on purpose: a missing source file is a pipeline problem,
    not something to paper over with an empty DataFrame later.
    """
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Source path is not a file: {path}")


def read_csv_records(path: Path) -> list[dict[str, str]]:
    """Read a CSV into a list of dicts (one dict per row) via csv.DictReader."""
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def inspect_columns(records: list[dict[str, str]]) -> list[str]:
    """Return the column names found in the first record."""
    if not records:
        return []
    return list(records[0].keys())


def write_manifest_entry(manifest_path: Path, result: IngestionResult) -> None:
    """Append this ingestion run's metadata to a JSON manifest.

    Demonstrates JSON read/write and doubles as the seed of pipeline
    monitoring (Phase 17) - "when was this file ingested, how many
    records did it have" answered without re-reading the raw file.
    """
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {"runs": []}

    manifest["runs"].append(asdict(result))

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def ingest_csv(source_path: Path, raw_dir: Path) -> IngestionResult:
    """Validate, read, and copy one source CSV into the raw data lake.

    Steps: validate file exists -> read CSV -> inspect columns ->
    report record count -> write a copy to raw storage -> log a
    manifest entry.
    """
    validate_file_exists(source_path)

    records = read_csv_records(source_path)
    columns = inspect_columns(records)

    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / source_path.name
    shutil.copy2(source_path, raw_path)

    result = IngestionResult(
        source_name=source_path.stem,
        source_path=str(source_path),
        raw_path=str(raw_path),
        columns=columns,
        record_count=len(records),
        ingested_at=datetime.now(timezone.utc).isoformat(),
    )

    write_manifest_entry(raw_dir / "_ingestion_manifest.json", result)

    logger.info(
        "Ingested %s: %d records, %d columns -> %s",
        source_path.name,
        result.record_count,
        len(columns),
        raw_path,
    )
    return result


def ingest_all(external_dir: Path, raw_dir: Path, filenames: list[str]) -> list[IngestionResult]:
    """Ingest each named CSV in external_dir into raw_dir."""
    results = []
    for name in filenames:
        source_path = external_dir / name
        try:
            results.append(ingest_csv(source_path, raw_dir))
        except (FileNotFoundError, ValueError) as exc:
            logger.error("Skipping %s: %s", name, exc)
    return results


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    external_dir = project_root / "data" / "external"
    raw_dir = project_root / "data" / "raw"

    source_files = ["yield.csv", "pesticides.csv", "rainfall.csv", "temp.csv"]
    results = ingest_all(external_dir, raw_dir, source_files)

    print(f"\nIngested {len(results)}/{len(source_files)} source files:")
    for r in results:
        print(f"  {r.source_name}: {r.record_count} records, columns={r.columns}")
