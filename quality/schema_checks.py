"""Phase 5 - schema validation: does this raw file even have the columns
we expect, before we try to run row-level business rules on it?

Concept: a "data contract" is an explicit, checkable agreement about what
a source is supposed to look like (columns, types) - schema validation is
enforcing that contract mechanically instead of discovering a broken
assumption three transformations downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class SourceSchema:
    source_name: str
    required_columns: list[str]


@dataclass
class SchemaResult:
    source_name: str
    passed: bool
    missing_columns: list[str] = field(default_factory=list)


# One schema per raw source (columns as they appear straight out of ingestion,
# before Phase 3's renaming) - this is deliberately checked upstream of
# transform.py, matching the architecture order: RAW -> QUALITY -> ETL.
SCHEMAS = {
    "yield": SourceSchema(
        "yield",
        ["Domain Code", "Domain", "Area Code", "Area", "Element Code", "Element", "Item Code", "Item", "Year Code", "Year", "Unit", "Value"],
    ),
    "pesticides": SourceSchema("pesticides", ["Domain", "Area", "Element", "Item", "Year", "Unit", "Value"]),
    "rainfall": SourceSchema("rainfall", ["Area", "Year", "average_rain_fall_mm_per_year"]),
    "temp": SourceSchema("temp", ["year", "country", "avg_temp"]),
}


def validate_schema(df: pd.DataFrame, schema: SourceSchema) -> SchemaResult:
    columns = {c.strip() for c in df.columns}
    missing = [c for c in schema.required_columns if c not in columns]
    return SchemaResult(schema.source_name, passed=not missing, missing_columns=missing)
