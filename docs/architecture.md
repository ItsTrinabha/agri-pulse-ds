# AgriPulse Architecture

## Logical pipeline

```
DATA SOURCES -> INGESTION -> RAW DATA LAKE -> DATA QUALITY -> (QUARANTINE | VALID)
   -> TRANSFORMATION/ETL -> CURATED DATA -> FEATURE ENGINEERING
   -> {YIELD MODEL, RISK MODEL, CLUSTERING MODEL} -> EXPLAINABILITY
   -> DECISION ENGINE -> API -> DASHBOARD
```

## Data zones

| Zone | Folder | Meaning |
|---|---|---|
| Source | `data/external/` | Untouched vendor/source files exactly as downloaded. Never edited. |
| Raw | `data/raw/` | Ingested copy of source data (same content, tracked with a run ID/timestamp) — the "raw data lake". |
| Quarantine | `data/quarantine/` | Records rejected by the Data Quality Engine, with a reject reason column. Nothing is silently deleted. |
| Processed | `data/processed/` | Curated, transformed, model-ready data (post-ETL, post-feature-engineering). |

## Why this separation

- **Source vs raw**: source files are external and can be re-fetched or replaced; keeping them separate from "raw" means ingestion (validation of file existence, structure) is a distinct, testable step from acquisition.
- **Raw vs processed**: raw preserves what we received, even if wrong — this is what lets us debug "why did this record get rejected" without re-downloading. Processed is what models/dashboards actually read.
- **Quarantine, not deletion**: a bad record is often a data quality *signal* (upstream bug, unit mismatch) — deleting it destroys the evidence needed to diagnose the source problem.

## Azure-ready mapping (conceptual — nothing below is deployed)

| Local component | Azure equivalent |
|---|---|
| CSV/API ingestion scripts | Azure Data Factory pipelines |
| `data/raw/`, `data/processed/` | Azure Data Lake Storage (bronze/silver/gold zones) |
| PySpark transformation | Azure Databricks |
| SQL layer | Azure SQL / Synapse / Fabric (TBD based on scale) |
| Model training/serving | Azure Machine Learning |
| Dashboard | Power BI or the Streamlit app behind App Service |
| Pipeline/model monitoring | Azure Monitor / Application Insights |

This mapping is aspirational documentation, not a deployment claim. Full detail (security/identity, a diagram, build ordering, and the reasoning behind each service choice): [`azure_architecture.md`](azure_architecture.md) (Phase 19).

## Decisions

See [`decisions.md`](decisions.md) for the running decision log with rationale (interview-defense format: problem / choice / alternatives / limitations).
