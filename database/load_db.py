"""Phase 4 - load the Phase 3 curated dataset into a normalized SQLite
database, then run the Phase 4 analytical queries against it.

SQLite (Python stdlib `sqlite3`, zero extra dependencies) is used rather
than a client-server database (Postgres/MySQL) - this is a local, single-
writer analytical workload; a server-based DB would be an unjustified
extra moving part for the MVP (spec: "no technology without a purpose").
The Azure-ready mapping documents how this becomes Azure SQL/Synapse
later (docs/architecture.md).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def create_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    conn.executescript(schema_path.read_text(encoding="utf-8"))


def load_curated_dataset(conn: sqlite3.Connection, curated: pd.DataFrame) -> None:
    regions = sorted(curated["area"].unique())
    crops = sorted(curated["crop"].unique())

    conn.executemany(
        "INSERT INTO region (region_name) VALUES (?)", [(r,) for r in regions]
    )
    conn.executemany(
        "INSERT INTO crop (crop_name) VALUES (?)", [(c,) for c in crops]
    )

    region_id = {name: i + 1 for i, name in enumerate(regions)}
    crop_id = {name: i + 1 for i, name in enumerate(crops)}

    # weather/practice are (region, year) grain - dedupe before insert,
    # since curated_dataset repeats the same weather value across every
    # crop row for that region-year (see schema.sql comments).
    region_year = curated.drop_duplicates(subset=["area", "year"])

    conn.executemany(
        "INSERT INTO weather_observation (region_id, year, rainfall_mm, avg_temp_c) VALUES (?, ?, ?, ?)",
        [
            (
                region_id[row.area],
                int(row.year),
                None if pd.isna(row.rainfall_mm) else float(row.rainfall_mm),
                None if pd.isna(row.avg_temp_c) else float(row.avg_temp_c),
            )
            for row in region_year.itertuples()
        ],
    )

    conn.executemany(
        "INSERT INTO agricultural_practice_observation (region_id, year, pesticides_tonnes) VALUES (?, ?, ?)",
        [
            (
                region_id[row.area],
                int(row.year),
                None if pd.isna(row.pesticides_tonnes) else float(row.pesticides_tonnes),
            )
            for row in region_year.itertuples()
        ],
    )

    conn.executemany(
        "INSERT INTO yield_observation (region_id, crop_id, year, yield_hg_ha) VALUES (?, ?, ?, ?)",
        [
            (region_id[row.area], crop_id[row.crop], int(row.year), int(row.yield_hg_ha))
            for row in curated.itertuples()
        ],
    )
    conn.commit()

    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ["region", "crop", "weather_observation", "agricultural_practice_observation", "yield_observation"]
    }
    logger.info("Loaded row counts: %s", counts)


def build_database(db_path: Path, curated_path: Path, schema_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()  # rebuild fresh each run - the DB is derived, reproducible from curated_dataset.csv

    curated = pd.read_csv(curated_path)

    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn, schema_path)
        load_curated_dataset(conn, curated)
    finally:
        conn.close()

    logger.info("Database written to %s", db_path)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    build_database(
        db_path=project_root / "data" / "processed" / "agri_pulse.db",
        curated_path=project_root / "data" / "processed" / "curated_dataset.csv",
        schema_path=project_root / "database" / "schema.sql",
    )
