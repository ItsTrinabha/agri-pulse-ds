# Data Dictionary — Phase 0 Source Inspection

## Source

Mirror of a merged FAO/World Bank-derived agricultural dataset:
https://github.com/StonageBanana/Crop-Yield-Prediction

Original upstream data: FAO (yield, pesticide use), World Bank-derived climate records (rainfall), a global temperature record (avg_temp). Downloaded 2026-09-01 into `data/external/` (untouched, gitignored — re-run the ingestion step to refetch).

Four independent raw files, deliberately **not** using the repo's pre-merged `yield_df.csv` — AgriPulse builds its own multi-source join (Phase 1 ingestion, Phase 3 Pandas merge) rather than consuming someone else's already-cleaned output. `yield_df.csv` is kept in `data/external/` only as a reference/sanity-check for the final merge.

## Source 1 — `yield.csv` (target variable)

| Column | Type | Meaning |
|---|---|---|
| Domain Code / Domain | str | FAO dataset domain, constant = "Crops" (QC) |
| Area Code / Area | int / str | Country/region identifier and name |
| Element Code / Element | int / str | Constant = "Yield" |
| Item Code / Item | int / str | Crop name — **10 unique crops**: Maize, Potatoes, Rice paddy, Wheat, Sorghum, Soybeans, Cassava, Yams, Sweet potatoes, Plantains and others |
| Year Code / Year | int | 1961–2016 |
| Unit | str | Constant = "hg/ha" (hectograms per hectare — 1 hg/ha = 0.1 kg/ha) |
| Value | int | **Target variable**: crop yield |

- Rows: 56,717. Areas: 212. No nulls.
- Grain: one row per (Area, Item, Year).

## Source 2 — `rainfall.csv`

| Column | Type | Meaning |
|---|---|---|
| Area (note: header has a leading space — `" Area"`) | str | Country/region |
| Year | int | 1985–2017 |
| average_rain_fall_mm_per_year | str (should be numeric) | Average annual rainfall, mm |

- Rows: 6,727. Areas: 217.
- **Data quality issue found in Phase 0 inspection**: 774 rows use the sentinel value `".."` for missing rainfall (a common FAO/World Bank "not available" code) instead of an empty cell — this is why pandas infers the column as `str` rather than `float`. Must be coerced to NaN, not treated as a literal string, during ingestion/quality checks (Phase 1/5).
- Column name has a leading space — must be stripped during ingestion.

## Source 3 — `temp.csv`

| Column | Type | Meaning |
|---|---|---|
| year | int | 1743–2013 |
| country | str | Country name |
| avg_temp | float | Average annual temperature, °C |

- Rows: 71,311. Countries: 137. 2,547 nulls in `avg_temp` (true NaNs, not sentinel-coded).
- Note: much longer year range than the other sources (historical back to 1743) — will be truncated to the overlapping year range at join time (Phase 3).

## Source 4 — `pesticides.csv`

| Column | Type | Meaning |
|---|---|---|
| Domain | str | Constant = "Pesticides Use" |
| Area | str | Country/region |
| Element | str | Constant = "Use" |
| Item | str | Constant = "Pesticides (total)" |
| Year | int | 1990–2016 |
| Unit | str | Constant = "tonnes of active ingredients" |
| Value | float | Pesticide use, tonnes |

- Rows: 4,349. Areas: 168. No nulls.

## Known cross-source caveats (to carry into Phase 1/3/5)

1. **Different year coverage per source** (1961–2016 yield vs 1990–2016 pesticides vs 1985–2017 rainfall vs 1743–2013 temp) — the eventual joined analytical dataset will be bounded by the narrowest overlap unless we accept nulls for years outside a source's range.
2. **Country/Area naming may not match exactly** across sources (e.g., "Côte D'Ivoire" spelling, historical vs current country names) — join keys need normalization before merging (Phase 3).
3. **Grain mismatch**: yield and pesticides are per (Area, Year[, Item] for yield); rainfall and temp are per (Area, Year) only — i.e. rainfall/temp do not vary by crop. This is realistic (weather doesn't depend on which crop you planted) but means the join is many-to-one for rainfall/temp.
4. **Rainfall missing-value sentinel (`".."`)** must be handled explicitly, not silently dropped.
5. **Units differ in scale**: yield in hg/ha (divide by 10 for kg/ha), pesticides in tonnes — no unit conflict across sources here, but must be stated explicitly rather than assumed.

These caveats are what the Data Quality Engine (Phase 5) and Transformation Pipeline (Phase 3) are specifically designed to handle — not incidental bugs to patch around.

## Curated dataset — `data/processed/curated_dataset.csv` (Phase 3 output)

Produced by `pipeline/transform.py`. Grain: one row per (area, crop, year) — same grain as `yield.csv`, with weather/pesticide data left-joined on (normalized area, year).

| Column | Type | Meaning |
|---|---|---|
| area | str | Country/region name (as given by `yield.csv`) |
| crop | str | One of the 10 crops |
| year | int | 1961–2016 |
| yield_hg_ha | int | Target variable — see D3.4 for flagged extreme values (0 to 1,000,000) |
| pesticides_tonnes | float | Nullable — 42.6% match rate (pesticides.csv only covers 1990–2016 and 168 of 212 yield areas) |
| rainfall_mm | float | Nullable — 48.6% match rate |
| avg_temp_c | float | Nullable — 65.2% match rate; aggregated from sub-annual readings, see D3.3 |

- Rows: 56,717 (matches `yield.csv` exactly — confirms the join is many-to-one, not fanned out; see D3.3 for the bug this caught).
- Full duplicate/null/join-rate metrics for this run: `data/processed/_transform_report.json`.
- Nulls in the three joined columns are **expected and meaningful** (a source simply doesn't cover that area/year) — not a defect to impute away silently. Imputation strategy, if any, is a Phase 5/12 decision.

## Data Quality Engine results (Phase 5)

Run via `python -m quality.quality_report`; full detail in `data/quarantine/_quality_report.json`, rejected rows in `data/quarantine/<source>_rejected.csv`.

| Source | Accepted / Total | Quality score | Status | Reasons |
|---|---|---|---|---|
| yield | 56,708 / 56,717 | 99.98% | PASSED | 1 implausible yield (Kenya/Plantains/1964, 1,000,000 hg/ha), 8 non-positive yields |
| pesticides | 4,349 / 4,349 | 100% | PASSED | — |
| rainfall | 6,727 / 6,727 | 100% | PASSED | — (missing values are NaN, not rejected — see below) |
| temp | 64,353 / 71,311 | 90.24% | PASSED_WITH_WARNINGS | 6,958 exact duplicate rows |
| **Overall** | **132,137 / 139,104** | **94.99%** | | |

Note: `Value`/`avg_temp`/`rainfall` nulls are *not* counted as rejections — a source not covering a given area/year is expected sparsity (see caveats above), not corruption. Quarantining those rows would just delete otherwise-valid yield observations because an unrelated weather source happened not to cover that row. This is a deliberate Phase 5 design choice — see `docs/decisions.md` D5.1-D5.3 for the reasoning, including a self-caught bug in an earlier version of the year-range rule.
