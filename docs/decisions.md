# Decision Log

Format per decision: Problem / Choice / Alternatives considered / Limitations (interview-defense standard, spec section 19).

---

## D0.1 — Project root location

**Problem**: Where should the AgriPulse codebase live relative to the spec documents?
**Choice**: New `agri-pulse/` folder alongside the four spec markdown files, with its own independent git repository.
**Alternatives**: Build inside the existing home-directory git repo (rejected — that repo already tracks unrelated personal files across the whole user profile; a nested independent repo keeps AgriPulse's history clean and portable/shareable on its own).
**Limitations**: The spec docs themselves live one level up, outside the project repo — referenced by relative mention in the README rather than committed inside it.

---

## D0.2 — Dataset selection

**Problem**: Need a legitimate, documented, multi-source, reproducible agriculture dataset per spec section "Dataset Policy".
**Choice**: FAO/World Bank-derived crop yield dataset (yield, pesticide use, rainfall, temperature as four separate raw files), mirrored at `github.com/StonageBanana/Crop-Yield-Prediction`. See `data_dictionary.md`.
**Alternatives considered**:
- Kaggle's pre-merged `yield_df.csv` directly — rejected as the primary source because it hides the multi-source join the spec explicitly wants us to build and learn (ingestion, schema validation, join-key normalization across 4 sources).
- A single-file dataset (e.g. Crop Recommendation dataset with N/P/K/rainfall/label) — rejected: it's built for crop *recommendation* classification with synthetic-looking soil values, not yield *regression* with real historical rainfall/temperature/pesticide time series, and it has only one source file (no multi-source ingestion story).
**Limitations**: Country/year-level granularity (FAO), not farm/field-level. Yield is a national average, so it cannot capture within-country regional variation. Temperature source has a much longer historical range (back to 1743) than the others, which will need bounding.

---

## D0.3 — Data zone separation (`external` vs `raw`)

**Problem**: Spec's recommended structure lists `data/raw/`, `data/processed/`, `data/quarantine/` but not a landing zone for vendor-original files.
**Choice**: Added `data/external/` as the landing zone for untouched source files (matches architecture section 8's "DATA SOURCES" box, distinct from "RAW DATA LAKE"). Phase 1's ingestion script will read from `external/`, validate, and write the tracked copy into `raw/`.
**Alternatives**: Download straight into `data/raw/` and treat that as both source and raw — rejected, it would blur "what we received" with "what ingestion validated and accepted," which is the point of Data Quality being a separate pipeline stage.
**Limitations**: One more folder than the spec's minimal listing; documented here so the deviation is intentional, not accidental.

---

## D0.4 — Data quality issues found during Phase 0 inspection (carried forward)

- `rainfall.csv` encodes missing values as the string `".."`, and its Area column header has a leading space. Both must be handled in ingestion/quality, not ignored.
- `temp.csv` has ~3.6% true NaNs in `avg_temp`.
- All four sources have different year coverage and must be joined on normalized (Area, Year[, Item]) keys.

Full detail in `data_dictionary.md`. These are exactly the kind of real-world messiness the Data Quality Engine (Phase 5) is designed to catch — not something to clean silently before the pipeline sees it.

---

## D1.1 — Phase 1 ingestion uses stdlib only, not pandas

**Problem**: The ingestion script needs to read CSV, validate, count records, and copy to raw storage.
**Choice**: Implemented with `csv`, `pathlib`, `json`, `shutil` (stdlib only) in `ingestion/csv_ingestion.py`.
**Alternatives**: Use pandas immediately — rejected for Phase 1 specifically, since the roadmap's point of this phase is understanding CSV/JSON/file/dict handling in raw Python before pandas is introduced as a productivity layer on top of it (Phase 3).
**Limitations**: `csv.DictReader` treats every field as a string — no type inference. Fine for ingestion (which shouldn't be doing type coercion anyway; that's a data-quality/transformation concern), but callers must cast fields themselves, as `phase1_exercises.py` does with `float(r["Value"])`.

## D1.2 — Observation flagged for later EDA (Phase 7)

Grouping Maize yield by area (plain-Python exercise) surfaced very high average yields for small Gulf states (UAE ~221,585 hg/ha, Kuwait ~140,004 hg/ha) versus typical values elsewhere. Plausible (small irrigated/greenhouse-intensive cultivated area skews the FAO national average up) but not yet verified — flagged to check for outliers/data errors during Phase 6/7 rather than assumed correct or incorrect now.

---

## D3.1 — "Mojibake" in Phase 0/1 terminal output was a display issue, not a data bug

**Problem**: `Côte d'Ivoire` printed as `C�te d'Ivoire` / `C?te d'Ivoire` when area names were dumped to the terminal.
**Investigation**: read the raw bytes of `yield.csv` directly — confirmed valid UTF-8 (`\xc3\xb4` = `ô`). The file is correctly encoded; Windows' cp1252 terminal just can't render it.
**Choice**: No fix needed in the data or the ingestion/transform code. Scripts avoid printing exotic-Unicode country names directly to the console where it matters; the CSV/curated files themselves are correct UTF-8.
**Why this is logged**: worth recording explicitly so a future "the data looks corrupted" report from the terminal isn't mistaken for a real defect again.

## D3.2 — Country-name join keys: small alias table, not a full solution

**Problem**: Sources use different country-name conventions (formal UN names in `yield.csv`/`pesticides.csv` like "Lao People's Democratic Republic" vs. common names like "Laos" elsewhere; historical entities like "USSR"/"Sudan (former)"/"Ethiopia PDR" with no modern equivalent).
**Choice**: `pipeline/transform.py::normalize_area()` lowercases/strips and applies a ~20-entry alias map for the most common formal-name mismatches (Vietnam, Laos, Bolivia, Moldova, DR Congo, Russia, etc.).
**Alternatives considered**: A full country-code (ISO 3166) mapping library — rejected as disproportionate for an MVP; would add a dependency to solve a problem that's better made *visible* (via the join match-rate report) than silently perfect-matched. Fuzzy string matching — rejected, risk of incorrectly merging two different countries is worse than a documented non-match.
**Limitations**: Historical entities (USSR, Sudan (former), Ethiopia PDR) are intentionally left unmatched — they don't have one unambiguous modern equivalent, and guessing one would be a silent, undocumented data decision. Reported quantitatively via `join_match_rates` in `data/processed/_transform_report.json` rather than assumed complete.

## D3.3 — `temp.csv` is sub-annual and must be aggregated before joining

**Problem**: First merge attempt produced a curated dataset with **121,936 rows** from a 56,717-row `yield.csv` — a many-to-one join fanned out into many-to-many. Diagnosed by checking for duplicate `(area_key, year)` groups per source: `temp.csv` had 7,625 such groups, up to 41 rows for the same country-year (e.g. United States/1982), with real seasonal variation (4.76-24.14°C) — not noise or exact duplicates.
**Choice**: `clean_temp()` now aggregates to one row per `(area_key, year)` via `groupby(...).mean()` before the merge, and the group key excludes `area` (display name) specifically so a spelling variant of the same normalized country can't leave two groups for the same year.
**Why this matters for the interview-defense standard**: this is the kind of bug that will not always throw an error — the join "succeeds" and produces a plausible-looking but wrong (fanned-out, row-duplicated) dataset. The row-count sanity check (curated rows should not exceed `yield.csv` rows, since yield is the finest grain) is what caught it.
**Limitations**: Averaging sub-annual readings to a yearly mean discards seasonal signal (e.g. a hot growing-season month averaged against a cold one) that could matter for yield prediction later — noted as a candidate feature-engineering improvement (Phase 12), not fixed here.

## D3.4 — Extreme yield values flagged, not cleaned, in Phase 3

`curated_dataset.csv`'s `yield_hg_ha` ranges from 0 to 1,000,000 (100 t/ha) — both ends are suspicious (a recorded zero-yield harvest; a yield far above realistic maxima for any of the 10 crops in this dataset). Left as-is in the curated dataset; flagged for the Data Quality Engine (Phase 5) to apply a defensible range check and for EDA (Phase 6/7) to investigate, rather than silently dropped or capped here.

---

## D4.1 — SQLite, not a client-server database

**Problem**: Phase 4 needs to "store curated agricultural data in a relational database."
**Choice**: SQLite via Python's stdlib `sqlite3` — `database/load_db.py` rebuilds `data/processed/agri_pulse.db` fresh from `curated_dataset.csv` on every run (the DB is a derived artifact, not a source of truth).
**Alternatives**: Postgres/MySQL — rejected for local MVP: this is a single-writer, read-mostly analytical workload with no concurrent-access requirement, so a server process would be an unjustified extra moving part. The Azure-ready mapping (`docs/architecture.md`) documents the eventual Azure SQL/Synapse/Fabric target for when that changes.
**Limitations**: SQLite has weaker concurrent-write support and fewer window-function/type features than Postgres, but every query in `database/queries.sql` (including CTEs and `RANK()`/`LAG()` window functions) runs on it unmodified — nothing used here actually needed a bigger engine.

## D4.2 — No `soil` table

Spec section 10 lists "soil observations" as a potential entity. Omitted here because none of the four source files contain soil data — adding a `soil` table with no data behind it (or worse, fabricated values) would violate the "never fabricate metrics" rule (spec section 17). If a soil dataset is added later (spec's Future Extensions), the table can be added then with a real source cited in `data_dictionary.md`.

## D4.3 — Weather/practice tables are (region, year) grain, deduplicated before insert

`curated_dataset.csv` repeats the same `rainfall_mm`/`avg_temp_c`/`pesticides_tonnes` values across every crop row for a given region-year (by construction of the Phase 3 join). `load_db.py` deduplicates on `(area, year)` before inserting into `weather_observation` and `agricultural_practice_observation`, so those tables hold each region-year fact once — normalized, per Phase 4's design goal — rather than one row per crop. Verified: 56,717 yield rows collapse to 10,572 region-year weather/practice rows.

---

## D5.1 — Self-caught bug: don't conflate "old" with "invalid" in a year-range rule

**Problem**: The first version of the year-plausibility rule used `MIN_PLAUSIBLE_YEAR = 1900` for every source. Running the Phase 5 engine on `temp.csv` rejected 31,981 records (45% of the file) as `year_out_of_range` — but those are genuine historical temperature readings back to 1743 (see Phase 0's data dictionary), not corrupted data.
**Root cause**: a validity rule ("is this year physically impossible, e.g. negative or in the future?") got conflated with an analysis-relevance rule ("is this year inside the range our yield model cares about, 1961+?"). The former belongs in the Data Quality Engine; the latter is a scoping decision that Phase 3's join already handles correctly (temp rows outside yield's year range simply don't get matched, they aren't wrongly deleted).
**Fix**: lowered `MIN_PLAUSIBLE_YEAR` to 1600 (a generous floor that only catches genuinely broken year values, e.g. 0 or negative) — `temp.csv`'s quality score went from 50.4% (misleadingly bad) to 90.2% (accurate: real issue is the 6,958 exact-duplicate rows, not the year range).
**Why this is logged**: exactly the kind of mistake the roadmap's "implement -> test -> break -> fix -> document" loop is meant to catch — a rule that looks reasonable in isolation but is wrong once run against real data, caught only by actually running it and questioning a suspicious number instead of accepting it.

## D5.2 — Global (not per-crop) implausible-yield ceiling

**Problem**: deciding an upper bound for `non_positive_yield`/`implausible_yield` checks on `yield_hg_ha`.
**Choice**: a single global ceiling of 800,000 hg/ha (80 t/ha) across all 10 crops.
**Alternatives considered**: a per-crop ceiling (e.g. a lower bound for Wheat than for Potatoes, since world-record intensive potato yields can legitimately approach 100 t/ha while a Wheat yield anywhere near that would be essentially impossible) — more precise, but rejected for the MVP as added complexity requiring a defensible ceiling *per crop* (itself a research task) instead of a coarse belt-and-suspenders check. Result: the engine caught the one genuinely implausible record (Kenya, "Plantains and others", 1964, 1,000,000 hg/ha) that D3.4 originally flagged, without needing crop-specific tuning.
**Limitations**: a moderately-implausible-for-its-crop-but-under-800,000 value (e.g. an 80 t/ha Wheat yield, which would be a world record several times over) would pass this check silently. Noted as a Phase 6/7 EDA follow-up (per-crop distribution review), not solved here.

## D5.3 — Resolution of D3.4's flagged extreme values

The Phase 5 engine traced Phase 3's flagged extremes to specific records: the single 1,000,000 hg/ha value is Kenya/Plantains and others/1964 (quarantined as implausible). The eight `yield_hg_ha == 0` records are Sorghum/Wheat in New Caledonia and Sorghum in Occupied Palestinian Territory — crops that are marginal or atypical for those regions, consistent with a genuine failed/negligible harvest rather than a data error, but quarantined anyway since a zero yield can't be used by a regression model meaningfully (see spec: "report accuracy for a regression problem" rule doesn't apply here, but a zero-yield row would still distort MAE/RMSE out of proportion to what it represents). All nine records: `data/quarantine/yield_rejected.csv`.

---

## D6.1 — Statistics run on pre-quarantine curated data (known gap, quantified as negligible)

`analytics/statistics.py` reads `data/processed/curated_dataset.csv` directly, which still includes the 9 records the Phase 5 engine quarantined (0.016% of 56,717 rows). Not fixed now because wiring quality-engine output back into the transform step is explicitly a Phase 15 ("refactor notebook work into pipeline stages") task, not a Phase 6 one — doing it piecemeal now would pre-empt that phase's actual learning goal. Quantified rather than hand-waved: 9/56,717 rows cannot materially shift a distribution with n=8,631 for a single crop.

## D6.2 — Negative rainfall/temperature correlation with Maize yield, flagged not explained

Maize yield correlates negatively with both rainfall (r=-0.15) and temperature (r=-0.45) across the 2,272 rows with complete weather data. Counter to a naive "more rain/warmth = more crop growth" intuition. Plausible explanation not confirmed here: the highest-yield regions in the Phase 6 report (UAE, Kuwait, Qatar, Israel) are hot, low-rainfall, and almost certainly irrigation-dependent — if so, the correlation is confounded by irrigation intensity/farming-system wealth, not a real negative causal effect of rain on maize. Explicitly not claimed as causal (spec section 6/9 rule) — flagged as a Phase 7 EDA question (does the negative correlation hold within-region, across years, rather than only across regions?) and a Phase 13 explainability question once a model exists.

---

## D7.1 — matplotlib only, no seaborn

**Problem**: Phase 7 needs several chart types (bar, scatter+trendline, boxplot, line).
**Choice**: matplotlib alone.
**Alternatives**: seaborn — rejected; its main value-add over matplotlib is nicer default styling and one-line statistical plot types, neither of which was needed here (a manual `np.polyfit` trendline and `ax.boxplot` cover everything required). Adding a dependency whose only benefit is aesthetics doesn't meet the "no technology without a purpose" bar.

## D7.2 — EDA confirmed, did not just illustrate, the Phase 6 rainfall confound

Q3's scatter plot (`03_rainfall_vs_yield.png`) visually shows the highest-yield Maize region-years clustering below 200mm/year rainfall — the same regions (UAE, Israel, Kuwait) flagged in D6.2 as likely irrigation-dependent. The correlation-by-crop chart (`04_rainfall_correlation_by_crop.png`) shows the negative correlation holds for 7 of 10 crops, not just Maize — strengthening rather than resolving the confound hypothesis (a real per-region time-series analysis is still needed to separate "dry regions are intensive" from "rain hurts yield," left for Phase 12/13).

## D7.3 — Root/tuber vs. grain yield is not a fair cross-crop comparison

Q1 found Potatoes yield (150,083 hg/ha) is ~10x Soybeans (14,163). This is a harvest-weight artifact (tubers are weighed fresh/wet, grains dry), not evidence potatoes are a more "productive" crop. Documented explicitly in `notebooks/phase7_eda_report.md` so this number isn't later misquoted out of context (e.g. in the README or an interview) as a real productivity comparison.

---

## D8.1 — Temporal train/test split, cutoff year 2005

**Problem**: how to split 1961-2016 data for model evaluation.
**Choice**: everything before 2005 is train (43,449 rows), 2005+ is test (13,268 rows, ~23%) — `models/evaluation.py::temporal_split`.
**Alternatives**: a random row-level split — rejected as the default: the real deployment question is "predict a future season's yield," and a random split would let the model train on Region X/2010 while being tested on Region X/2008, which no real forecast deployment could ever do (implicit future leakage). A random split will still be shown once in Phase 9 as an explicit, labeled comparison to make the leakage effect visible, not used as the primary evaluation.
**Limitations**: a single fixed cutoff means test performance is somewhat sensitive to which years land in the window (e.g. a run of unusual weather years in the test period); cross-validation in Phase 9 uses multiple folds to partially address this, still respecting time order.

## D8.2 — Baseline is (region, crop) historical average, not a global mean

A single global mean-yield baseline would be trivially easy to beat (it ignores that Potatoes and Soybeans differ by ~10x, per D7.3) and would overstate how much value a real model adds. The (region, crop) historical-average baseline (with crop-mean and global-mean fallbacks for cold-start pairs) is a meaningfully harder target — R²=0.72 already — so Phase 9's models have to demonstrably add value from rainfall/temperature/pesticide features, not just from knowing "this is Belgium growing Potatoes."

---

## D9.1 — Feature set and leakage rules (`models/yield_model.py::FeatureBuilder`)

**Features**: year; rainfall/temp/pesticides (median-imputed on train, each with a `*_missing` indicator since missingness is itself informative per Phase 7 Q5); crop (one-hot, 10 categories); `region_mean_yield` (train-only mean encoding — chosen over one-hot for `area` because 212 categories would be unwieldy for a linear model and mostly noise for a tree); `lag1_yield` (this region-crop's *actual* yield the year before).
**Leakage rules enforced**: every train-derived statistic (medians, region means) is fit on `train_raw` only, then applied to test — never re-fit or re-computed on the combined data. `lag1_yield` looks up year-1's *already observed* yield, which is legitimately known at prediction time in a real forecasting deployment (unlike using the current year's own yield, or a future year's).
**Why this matters**: a model fit on leaked information looks great on paper and fails in production, where the "future" information wouldn't exist yet - the entire structure here exists to make that mistake structurally hard to make by accident.

## D9.2 — Model comparison result and interpretation

| Model | Test MAE | Test R² |
|---|---|---|
| Baseline (Phase 8) | 24,366.5 | 0.7212 |
| Linear Regression | 7,869.4 | **0.9560** |
| Ridge (α=10) | ~same as LR | ~same |
| Decision Tree (unconstrained) | 13,529.2 | 0.8853 |
| Decision Tree (max_depth=8) | 8,048.1 | 0.9429 |
| Random Forest (tuned, CV-selected) | 7,412.7 | 0.9549 |

**Chosen model for downstream phases (13/14): the tuned Random Forest**, not Linear Regression, despite Linear Regression's marginally higher test R² (0.9560 vs 0.9549). Reasoning: (1) the gap is within noise given a single temporal holdout window (D8.1's limitation); (2) Random Forest gives built-in, well-understood feature importances for Phase 13's explainability layer, where Linear Regression's coefficients would need standardization to be comparably interpretable across features on very different scales; (3) Random Forest makes fewer distributional assumptions (no linearity/homoscedasticity requirement), which matters given the right-skewed yield distribution found in Phase 6. This is a defensible-tradeoffs choice, not a "highest number wins" choice (spec section 5 rule).
**Why Linear Regression is competitive at all**: `lag1_yield` and `region_mean_yield` are strong, close-to-linear predictors on their own (a region/crop's yield next year is usually close to this year's) - there isn't much nonlinear structure left for a tree ensemble to exploit beyond what a linear model already captures. This is a real, interview-ready finding, not a modeling mistake.
**Cross-validation note**: `TimeSeriesSplit` (not shuffled `KFold`) was used for the Random Forest hyperparameter search specifically to respect D8.1's leakage rule during tuning too, not just at the final train/test split.

## D9.3 — Overfitting demo confirms the concept concretely

Unconstrained Decision Tree: train R²=1.0000 (perfectly memorized every training row), test R²=0.8853 (a real but much weaker fit) - the textbook overfitting signature: near-zero train error paired with a materially worse test error. Limiting `max_depth=8` narrows that gap (train R²=0.9516, test R²=0.9429) at the cost of some training fit, which is the entire point of regularization/depth-limiting: trading training accuracy for generalization.

---

## D10.1 — Risk target: crop-relative underperformance, not an invented disease/drought label

**Problem**: spec section 5 (Model B) explicitly forbids "inventing a scientifically invalid disease target from unrelated data" — this dataset has no disease, drought, or pest information at all.
**Choice**: `models/risk_model.py::label_risk` — "high risk" = 1 if a (region, crop, year)'s yield falls below that **crop's own** 25th percentile, with the threshold computed on **training data only** per crop (not a single global percentile, since a low Soybean yield and a low Potato yield are different absolute numbers — D7.3).
**Alternatives considered**: a drought-risk label inferred from low rainfall — rejected: rainfall alone doesn't establish drought (soil moisture, irrigation access, timing within the growing season all matter, none of which this dataset has), so labeling it "drought risk" would overstate what's actually measured. The chosen label instead names exactly what it is: a realized-yield underperformance flag relative to crop-typical outcomes.
**Limitations**: this is a retrospective/diagnostic label (did this year underperform), not a leading indicator of drought or disease specifically — framed in the dashboard (Phase 20) as "yield risk," not "drought risk" or "disease risk," to avoid implying a causal mechanism the data can't support.

## D10.2 — Why accuracy is misleading here, demonstrated not just asserted

Class balance: 25.0% high-risk in train, 15.7% in test (the shift itself reflects the post-1990 yield increase from D8.1/D6 — train includes more of the lower-yielding pre-1990 years). A dummy classifier that always predicts "low risk" scores **84.3% accuracy** while catching **zero** of the real high-risk cases (recall=0.0, ROC-AUC=0.5, i.e. no better than a coin flip) — logged in `models/risk_model.py`'s own printed output specifically so this comparison is never skipped. Every real model is judged against this dummy floor, not against 0%.

## D10.3 — Model comparison and the precision/recall tradeoff

| Model | Accuracy | ROC-AUC | High-risk recall | High-risk precision |
|---|---|---|---|---|
| Dummy (majority class) | 0.843 | 0.500 (chance) | 0.00 | n/a |
| Logistic Regression | 0.944 | 0.975 | 0.68 | 0.94 |
| Logistic Regression (class_weight=balanced) | 0.934 | 0.976 | **0.92** | 0.73 |
| Decision Tree (max_depth=8) | 0.948 | 0.946 | 0.79 | 0.87 |
| Random Forest | 0.937 | **0.973** | 0.65 | 0.92 |

`class_weight="balanced"` on Logistic Regression is the clearest illustration of the precision/recall tradeoff: recall on the high-risk class jumps from 0.68 to 0.92 (misses far fewer real risk cases) at the cost of precision dropping from 0.94 to 0.73 (more false alarms). Which is preferable is a business decision, not a modeling one: missing a real agricultural risk (false negative) is plausibly more costly than one extra false alarm a decision-maker double-checks — so the balanced variant is the one carried forward to the dashboard (Phase 20), documented here so that choice is explicit rather than accidental.
**Feature scaling note**: `LogisticRegression` initially failed to converge (lbfgs, 1000 iterations) because `year` (~1961-2016) and yield-derived features (tens of thousands) differ by ~1000x in scale, which distorts gradient step sizes. Fixed by fitting a `StandardScaler` on train and applying it to both splits before the two logistic regression variants — tree models are scale-invariant (they split on raw per-feature thresholds) and don't need this.

---

## D11.1 — K=4 chosen over the silhouette-maximizing K=8

**Problem**: choosing K for K-Means over (rainfall, avg_temp, pesticides), scaled.
**Data**: silhouette scores for K=2..8 were 0.377, 0.405, **0.425**, 0.417, 0.423, 0.401, **0.430** — K=8 scored marginally higher (0.430) than K=4 (0.425), and inertia (elbow) drops sharply through K=4 then flattens.
**Choice**: K=4 anyway, not the silhouette-maximizing K=8.
**Reasoning**: (1) the elbow bends clearly at K=4 (inertia drop of 1,216 from K=3→4 vs. only ~400 from K=4→5); (2) the silhouette gap between K=4 and K=8 (0.425 vs 0.430) is small enough not to override interpretability; (3) spec section 5 requires clusters to be "interpreted in business terms" — 4 clusters produce a usable narrative (see D11.2), while 8 would fragment the already-small 33-region-year cluster further into groups too small to generalize from. This is a deliberate, documented trade of a marginally better internal metric for external usefulness — exactly the kind of judgment call an interview question ("why didn't you just pick the K with the best score?") is testing for.
**Limitations**: only 2,494 of the dataset's 10,572 region-years have complete rainfall+temp+pesticide data (the rest are excluded, not imputed — imputing conditions data specifically to make clustering "work" would manufacture the groupings being discovered). The clustered subset is therefore skewed toward 1990+ (per Phase 7 Q5's coverage-by-decade finding) and may not represent earlier-decade farming conditions.

## D11.2 — Cluster interpretation (business terms) and a cross-source scale caveat

| Cluster | Rainfall | Temp | Pesticides (total tonnes) | n | Mean yield z-score | Interpretation |
|---|---|---|---|---|---|---|
| 1 | 870mm | 10.2°C | 15,028 | 1,002 | **+0.88** | Cool-temperate, moderate rainfall, low absolute pesticide volume, **highest-yielding** cluster |
| 2 | 1,032mm | 17.6°C | 375,068 | 33 | +1.35 | Small, warm, extreme national pesticide *volume* — see caveat below |
| 0 | 570mm | 22.2°C | 7,341 | 870 | +0.04 | Hot, semi-arid, near-average yield |
| 3 | 2,030mm | 25.1°C | 10,906 | 589 | +0.09 | Hot, tropical/high-rainfall, near-average yield |

**Cross-check with Phase 7**: cluster 1 (cool-temperate, high-yield) is consistent with Q2's independently-derived finding that Belgium/Netherlands/UK/Denmark lead cross-crop standardized yield — two different unsupervised/descriptive methods pointing the same direction is a real (not circular — clustering used none of Phase 7's regional-ranking logic) corroboration.
**Caveat on cluster 2**: `pesticides_tonnes` is each country's **total national volume**, not per-hectare intensity (no cultivated-area normalization exists in this dataset — see `docs/data_dictionary.md`). Cluster 2's extreme value (375,068 vs. 7,000-15,000 elsewhere) most likely reflects a handful of very large agricultural economies (e.g. the US, China, India, Brazil) in absolute terms, not unusually intensive farming per hectare. Labeled here as "extreme national pesticide volume," not "highly intensive farming," to avoid the same kind of scale-artifact misreading D7.3 flagged for cross-crop yield.

---

## D12.1 — Feature engineering moved to its own module (`features/feature_engineering.py`)

**Problem**: `FeatureBuilder` had been living inside `models/yield_model.py` since Phase 9 and was imported sideways into `models/risk_model.py` — feature engineering and model training were tangled into one file, against the project's own directory structure (spec section 15 separates `features/` from `models/`).
**Choice**: moved `FeatureBuilder` to `features/feature_engineering.py`, imported from there by both `yield_model.py` and `risk_model.py`. Single source of truth for feature logic, matching the repo's declared structure.
**Two new engineered features added at the same time** (Phase 12's "ratios" and "temporal features" learn topics): `is_post_1990` (encodes the structural break found in Phase 6's t-test and Phase 7 Q5's coverage finding) and `yield_trend_ratio = lag1_yield / region_mean_yield` (is this region-crop currently trending above or below its own long-run average).
**Leakage check, run not just asserted**: `assert_no_target_leakage()` verifies no feature is byte-identical to the target and no feature has a suspiciously perfect (|r|>0.999) correlation with it — a real predictive feature is expected to correlate; a *perfect* one almost always means an indexing bug reused the current row's own target. Passed on all 22 engineered features.

## D12.2 — Honest result: the two new features barely moved the needle, and that's informative too

Re-running Phase 9/10's models after the refactor:

| Model | Test R²/AUC before D12.1 | after D12.1 |
|---|---|---|
| Linear Regression (yield) | R²=0.9560 | R²=0.9552 |
| Random Forest (yield) | R²=0.9549 | R²=0.9542 |
| Random Forest (risk) | ROC-AUC=0.9731 | ROC-AUC=0.9746 |

Yield-model performance is essentially unchanged (within noise); risk-model Random Forest accuracy improved modestly (0.937→0.949). **Not claimed as a meaningful yield-model improvement** — `is_post_1990` is a coarser version of information `year` already provided, and `yield_trend_ratio` is a ratio of two features (`lag1_yield`, `region_mean_yield`) that were already both present individually, so a tree/linear model had already been able to combine them implicitly. This is a real, useful finding to be honest about: **not every plausible-sounding engineered feature adds value**, especially a derived transform of features the model already has direct access to — the exit-criteria question ("why must features be available at prediction time") is answered by the leakage check; this is the separate, equally real lesson that engineering a feature isn't the same as it mattering.

---

## D13.1 — Major finding: the yield model is overwhelmingly a persistence model

**Finding**: `lag1_yield` accounts for **98.2%** of impurity-based importance and, even more strikingly, has a *larger* permutation-importance score (1.804) than the model's total R² would suggest is possible for a "fair share" — i.e. shuffling `lag1_yield` alone destroys most of the model's predictive power. Every other feature (rainfall, temperature, pesticides, crop, year) together accounts for under 2%. Confirmed per-prediction: both worked SHAP examples show `lag1_yield` contributing ~97-99% of the total deviation from the base rate, with weather/practice features contributing three to four orders of magnitude less.
**Interpretation, stated carefully**: the Random Forest has effectively learned "next year's yield ≈ a function of last year's yield," not a rich model of *why* yield is what it is. This is not a bug — year-over-year yield autocorrelation is a real, strong signal in national agricultural statistics — but it means the model's practical value is closer to "smoothed extrapolation" than "captures the effect of weather/inputs on yield."
**Consequences flagged for later phases**:
- **Phase 14 (what-if simulator)**: changing rainfall/temperature/pesticides in a scenario will move the prediction only slightly, because the model barely uses them. This must be stated explicitly in the simulator's UI, not discovered as a surprise — a user who expects a big response to a rainfall change and gets almost none needs to understand why.
- **Phase 18 (model monitoring)**: a model this reliant on one lagged feature is fragile exactly where that feature is unavailable (a genuinely new region-crop pair with no prior-year record - the 184 cold-start rows found in Phase 8) - worth watching in production.
- **Not a reason to discard the model**: it still beats the historical-average baseline (D8.2) meaningfully (R²=0.72→0.95), and "recent value plus a small correction from other factors" is a legitimate, common real-world forecasting pattern - just one that should be described accurately, not oversold as "the model understands what drives yield."

## D13.2 — SHAP TreeExplainer chosen over a manual perturbation method

**Choice**: `shap.TreeExplainer` on the tuned Random Forest, rather than hand-rolling a "how does prediction change if this feature were at its average" approximation.
**Reasoning**: SHAP's Shapley-value formulation has a real guarantee a manual perturbation method doesn't - contributions are computed to sum exactly to (prediction − base rate), and are consistent regardless of feature order, which is what makes "these are the top factors for this specific prediction" a well-defined statement rather than an ad hoc heuristic. `TreeExplainer` specifically is fast/exact for tree ensembles (no sampling approximation needed), so the added dependency has a concrete, non-cosmetic justification (spec's "no technology without a purpose" rule).
**Language discipline enforced in code, not just prose**: every printed explanation and chart caption uses "pushed prediction up/down," "associated with," never "caused" or "drove up" - spec section 6's wording rule is applied at the string-template level so it can't accidentally slip in later.

---

## D14.1 — What-if engine confirms D13.1 directly, with an honest example choice

**Confirmed**: a 15-case random sample of rainfall sensitivity (0.5x-1.5x multiplier) found spreads ranging from exactly **0** hg/ha (several cases - the instance's tree path never splits on rainfall) up to ~1,100 hg/ha on yields in the tens-to-hundreds-of-thousands - i.e. under 1% of baseline in every case checked. This is D13.1's finding, independently re-derived from a different angle (perturbing real inputs through the full pipeline, not inspecting the trained model's internals).
**Example choice, made transparently**: the first candidate tried (median-indexed row) showed *exactly* 0.00% change across the entire range - the strongest possible illustration of D13.1, but risked reading as a bug rather than a finding in a demo script. Switched to Italy/Sweet potatoes/2013 (0.8% total swing, independently verified non-cherry-picked via the same 15-case sample), which shows the same conclusion more legibly. Both are documented here rather than silently picking whichever looked better.
**Chart-integrity catch**: the first version of the sensitivity chart auto-scaled its y-axis to the ~1,600 hg/ha range of variation (out of a ~197,000 hg/ha baseline), which made a genuinely flat response look like sharp mountains - the opposite of what the chart was built to show. Fixed by anchoring the y-axis at 0. Logged because it's a real, easy-to-make data-visualization mistake (the numbers were never wrong, only the visual impression), not a one-off.

## D14.2 — Only rainfall/temperature/pesticides are user-overridable

Matches spec section 7's own worked example (it varies rainfall and fertilizer, not crop choice or region). `crop`, `area`, `year`, and the history-derived features (`lag1_yield`, `region_mean_yield`) are held fixed to the real historical record for the chosen (area, crop, year) — a what-if scenario answers "what if the weather/inputs had been different for this actual situation," not "what if this were a different crop or a different region's history." Every scenario result is printed with the Phase 14 exit-criteria disclaimer (`DISCLAIMER` constant, not just a comment) stating the output is a model-based estimate, not a guaranteed real-world outcome.

---

## D15.1 — D6.1's gap closed: quality-accepted data now actually feeds transform

**Problem**: since Phase 3, `pipeline/transform.py` read straight from `data/raw/*.csv`, never from the Phase 5 Data Quality Engine's accepted output — flagged as a known gap in D6.1 ("quantified as negligible," not fixed) and carried through Phases 6-14.
**Fix**: `pipeline/pipeline.py` runs all four stages in the architecture's actual order (ingestion → quality → transform → SQL load), passing `quality.quality_report.run_all()`'s **accepted DataFrames** directly into a new `pipeline.transform.build_curated_dataset_from_frames()` — no intermediate file round-trip, no re-reading raw CSVs post-quality-check. `run_quality_checks()` and `run_all()` were changed to return `(report, accepted_df)` instead of just the report, specifically so this could be wired in-memory.
**Measured effect**: curated dataset shrank from 56,717 to **56,708** rows — exactly the 9 quarantined yield records (D5.3), nothing more. `temp.csv`'s 6,958 rejected duplicate rows didn't change the yield-grain row count (they only reduce how many region-years have a weather match, already reflected in the join-match-rate metric). This confirms D6.1's "negligible" claim was correct, but it's now *verified*, not assumed.
**Backward compatibility**: `build_curated_dataset(raw_dir)` (Phase 3's original, unfiltered entrypoint) still works unmodified for direct `python -m pipeline.transform` runs — useful for debugging a transform issue in isolation from the quality stage.
**Not retroactively re-run**: Phases 6-14's reported numbers (statistics, EDA charts, model metrics, SHAP values) were generated on the pre-fix 56,717-row dataset and are left as originally reported, labeled to their phase, rather than re-running eight phases of analysis for a 0.016% row-count change with no material effect on any documented finding. `models/yield_model.py` was smoke-tested against the regenerated dataset to confirm it still runs correctly end to end.

## D15.2 — ETL not ELT; batch not streaming (stated, not just implied)

**ETL chosen**: `pipeline.py` transforms in pandas *before* loading into SQLite, rather than loading raw data into SQL and transforming there (ELT). Justified by data volume — tens of thousands of rows fit comfortably in memory, so there's no reason to push transformation work into the warehouse; ELT earns its keep at volumes where the warehouse's distributed compute is cheaper/faster than a single Python process, which doesn't apply here.
**Batch, not streaming**: the pipeline runs on-demand over static files, not against a continuous event source. `docs/architecture.md`'s Azure mapping documents what a streaming variant would look like (Event Hub → Databricks structured streaming) as a conceptual extension, not something implemented — spec's Azure-integrity rule (never claim deployment or capability that doesn't exist).
**Orchestration**: a single Python entrypoint (`run_pipeline()`) rather than an external scheduler (Airflow/Dagster/ADF) — appropriate for a project run on-demand during development; the Azure mapping names Azure Data Factory as the eventual orchestration layer, not built here.

---

## D16.1 — Measured result: Spark is ~44x slower than pandas on this dataset, as expected

**Measurement**: `pipeline/spark_pipeline.py`'s full run (session startup + build the transform plan + `count()` + write) took **33.99s**. The equivalent `pipeline.transform.build_curated_dataset()` (pandas) took **0.78s**, both producing the identical 56,717-row result. Spark session startup alone (12-17s across runs) exceeds the pandas job's *entire* runtime by more than an order of magnitude.
**Why, precisely**: Spark's cost here is almost entirely fixed overhead that doesn't depend on data size - JVM startup, Catalyst query planning/codegen, and (for `inferSchema=True`) an extra scan pass per CSV just to detect column types. None of that overhead amortizes on a 57k-row job; it would amortize on a job where the actual computation (shuffles, joins, aggregations across many partitions/executors) takes minutes-to-hours, at which point Spark's parallelism start paying for its own setup cost.
**This is the Phase 16 exit criteria answered concretely, not asserted**: Spark is useful once data no longer fits comfortably in one machine's memory, or a job is inherently parallelizable and slow enough that distributing it across a real multi-node cluster's cores saves more wall time than the fixed overhead costs. This dataset is neither - pandas remains the pipeline's real transform stage (`pipeline/transform.py`); `spark_pipeline.py` exists to learn Spark, not to replace it.

## D16.2 — Windows-only environment issues encountered, and why they don't apply to the real deployment target

Getting a local Spark session running on this Windows machine surfaced three genuinely Windows-specific issues, none of which are Spark's fault and none of which would occur on the Linux-based clusters (Databricks, EMR, on-prem YARN) `docs/architecture.md`'s Azure mapping targets:

1. **Batch-script parenthesis bug**: Spark's Windows launcher (`spark-class2.cmd`) uses `if (...) else (...)` blocks; when `JAVA_HOME` itself contains literal parentheses (`C:\Program Files (x86)\...`), cmd.exe's parser breaks mid-block. Root cause traced by reproducing the failure with a minimal script, not guessed at. Worked around with an 8.3 short path (`PROGRA~2`) for `JAVA_HOME`.
2. **`winutils.exe`/Hadoop requirement for local file writes**: Spark's DataFrameWriter goes through Hadoop's `LocalFileSystem`, which calls a Windows-only helper binary (`winutils.exe`) just to set file permissions when creating an output directory - unrelated to Spark's actual data processing. Rather than install more Windows-only plumbing for a local demo, `spark_pipeline.py` catches this specific failure and falls back to `collect()` + a pandas `to_csv()` (see the code comment referencing this section) - a real, common pattern for a final result already known to be small enough to bring back to the driver.
3. **`toPandas()` breaks on Python 3.12**: PySpark 3.5.x's `toPandas()` calls a version-check helper that imports `distutils`, which Python 3.12 removed from the standard library - unrelated to Spark or pandas themselves, a stdlib deprecation landing between the two libraries' release cadences. Worked around by using `collect()` (a plain Spark action with no such dependency) and building the pandas DataFrame directly from the collected rows.

**Also required**: downgrading from PySpark 4.2.0 (the version `pip install pyspark` installed by default) to **3.5.3**, since Spark 4.x requires Java 17+ and this machine only has Java 8 (`java version 1.8.0_491`) installed. Installing a JDK 17 system-wide was avoided as an unnecessarily invasive fix for a local learning exercise; pinning `pyspark==3.5.3` (Java 8-compatible) in `requirements.txt` is a self-contained, reversible choice within the project's own venv.

**Why this is worth documenting at all**: this is exactly the kind of "how would this fail / what's a limitation" interview question (spec section 19) that's better answered from genuine hands-on debugging than from a description of Spark in the abstract - and it's a fair, common real-world experience for anyone running Spark locally on Windows for the first time, not a sign the tool is broken.

---

## D17.1 — Monitoring history lives in its own database, never agri_pulse.db

**Problem**: where to persist pipeline run history (run ID, timing, record counts, status, errors) so past runs — especially failures — can be inspected later.
**Choice**: a dedicated `data/processed/monitoring.db` (`monitoring/pipeline_monitor.py`), append-only.
**Why not agri_pulse.db**: `database/load_db.py::build_database` deliberately `unlink()`s and rebuilds `agri_pulse.db` from scratch on every pipeline run (D4.1 - it's a derived, reproducible artifact, not a source of truth). Monitoring history needs the *opposite* property: it must survive every run, or "what happened across the last 10 runs" becomes unanswerable. Putting both in the same file would silently wipe monitoring history on every successful pipeline run - a subtle bug that would only surface the first time someone actually needed the history.

## D17.2 — Induced-failure demo required removing BOTH the external and raw copies

**First attempt** only removed `data/raw/temp.csv`, expecting the quality stage to fail on a missing file. It didn't - because `pipeline.pipeline.run_pipeline()` runs **ingestion first**, and `ingestion.csv_ingestion.ingest_all()` simply re-copied `data/external/temp.csv` back into `data/raw/temp.csv`, silently undoing the induced failure before the quality stage (which is what actually errors on a missing raw file) ever ran.
**Fix**: renamed both the `external/` and `raw/` copies aside before the demo run, and restored both afterward in a `finally` block regardless of outcome.
**Why this is worth keeping in the log**: it's a real, small lesson about testing failure injection in a multi-stage pipeline — a fault has to be introduced *upstream of every stage that could self-heal it*, not just at the stage expected to fail. Verified working: the second run correctly recorded `status=FAILED` with a full traceback in `error_message`, retrievable via `diagnose_last_failure()`, and the first (external) file removal was logged by ingestion's own per-file error handling (`ERROR: Skipping temp.csv: ...`) without crashing the ingestion stage itself - only the quality stage's stricter (uncaught) file read raised, which is the correct place for a genuinely missing required source to become a hard failure.

---

## D18.1 — PSI and KS-test disagree on `lag1_yield`, and that disagreement is the finding

Both metrics were computed deliberately, not just one, because they measure different things: PSI compares proportions across REFERENCE-defined quantile bins (can under-detect a broad, roughly-uniform shift if the same relative bin *proportions* happen to be preserved); the KS statistic is the max distance between the two empirical CDFs directly (more sensitive to a pure location shift). Result for `lag1_yield`: PSI=0.078 ("no significant shift") but KS p-value ≈ 0 (highly significant) despite the mean rising ~30% (57,719 → 74,819 hg/ha) between train and test periods — consistent with D8's post-1990 yield-increase finding (D6/D8.1), a real, expected shift, just one PSI's binning happened to under-weight. **Lesson**: a monitoring system that reports only one drift metric can miss what a second, differently-sensitive metric would catch — reported both rather than picking a favorite.

## D18.2 — Rainfall/pesticide "drift" is partly an imputation-composition artifact, not purely environmental

`rainfall_mm` (PSI=0.64) and `pesticides_tonnes` (PSI=0.84) show the largest drift by far — but the reference (train, 1961-2004) period includes ~30 years (1961-1984) where `rainfall.csv` has **zero** coverage and ~15 years (1961-1989) where `pesticides.csv` has zero coverage (Phase 7 Q5's coverage-by-decade finding), meaning most of the "reference" distribution for these two features is the imputed train median (`FeatureBuilder`'s `*_missing` + median-fill strategy, D9.1), not real measurements. The test period (2005+) has much better real coverage. So a large share of this "drift" is really a **change in how much of the reference vs. current data was imputed**, not necessarily a change in true underlying rainfall/pesticide-use distributions. Stated explicitly rather than reported as a clean "the world changed" finding — an accurate root-cause explanation is worth more than an alarming-sounding number left unexplained.

## D18.3 — Prediction drift stayed low despite large feature drift — confirms D13.1, doesn't just repeat it

Prediction-distribution PSI (early vs. late test period) is **0.0054** ("no significant shift"), even though the two features that drifted most (rainfall, pesticides) did so substantially (D18.2). This is exactly what D13.1's finding (the model relies on `lag1_yield` for ~98% of its weight) predicts should happen — upstream feature drift in a feature the model barely uses shouldn't move its output much, and it didn't. Independently confirmed here from monitoring-side evidence, not asserted from the explainability-side finding alone.

## D18.4 — Performance held up over the 12-year test window; the naive retraining rule still fired

R² across four 3-year test buckets: 0.964 → 0.958 → 0.952 → 0.945 → 0.961 (last partial bucket) - a total drift of only -0.003 from first to last, i.e. **no meaningful performance degradation** over 12 years, consistent with D18.3 (the model's dominant feature, `lag1_yield`, isn't drifting in a way that would hurt it).
**But** the illustrative retraining-trigger rule (`monitoring/model_monitor.py`, "flag if any feature's PSI ≥ 0.25 OR test-period R² drops below 0.85") **still fired**, because `rainfall_mm` and `pesticides_tonnes` crossed the PSI threshold — despite performance being fine. **This is a deliberate, honest limitation, not a bug to hide**: a naive rule that treats every feature's drift as equally important will false-positive on drift in a feature the model doesn't actually rely on. A better rule would weight each feature's drift by its Phase 13 permutation importance before deciding to flag — not implemented here (would be real added complexity for a monitoring system with no real production traffic to trigger it on), but named explicitly as the concrete next improvement, which is exactly the kind of answer spec section 19's "how would you improve it?" question is looking for.

---

## D19.1 — Azure mapping expanded into its own document, with an explicit build order

**Problem**: Phase 0's brief Azure mapping table (`docs/architecture.md`) satisfied "mention the cloud target" but not Phase 19's fuller learning objectives (storage, compute, warehouse, monitoring, identity/security, and being able to "draw and explain" the architecture).
**Choice**: `docs/azure_architecture.md` — full component mapping with reasoning per service (not just a name), a security/identity section (Key Vault, Managed Identity, RBAC, private endpoints) even though nothing local currently needs a secret, a Mermaid architecture diagram, and — the part most likely to matter in an actual interview — an explicit **build order** (ADLS+ADF first, Azure SQL when concurrency becomes the real constraint, Azure ML when something needs to call a live model, Databricks only if data volume actually crosses the point D16.1 measured, dashboard last).
**Why the build order matters more than the diagram**: spec section 19's interview-defense standard asks "how would this scale / how would this be deployed," not just "what does the diagram look like" — a migration plan ordered by which constraint actually bites first (SQLite's single-writer limit, per D4.1) is a materially better answer than "move everything to Azure at once."
**Integrity maintained**: every Azure service named is explicitly framed as "would map to" / "conceptually," consistent with spec's Azure-integrity rule and the "PROJECT COMPLETION STANDARD" instruction not to claim a deployment that didn't happen — nothing in this project is deployed to Azure.

---

## D20.1 — Verified the dashboard with Streamlit's official AppTest framework, not just "it starts"

**Problem**: confirming a Streamlit app actually works requires more than a clean process start — `streamlit run` serves a static JS shell immediately; the Python script itself only executes once a browser establishes a WebSocket session and sends a render request. A plain `curl localhost:8501` returning HTTP 200 (which it did) only proves the static asset server is up, not that `dashboard/app.py` runs without a runtime exception.
**Caught empirically**: added a temporary print marker after the module-level data/model loading code, restarted the server, and confirmed via the server log that the marker never printed after a plain HTTP GET — proof the script had NOT actually executed, contrary to what the "HTTP 200" result alone would suggest.
**Fix**: used `streamlit.testing.v1.AppTest` (Streamlit's own headless testing API, no browser or WebSocket protocol needed) to actually run the script and switch through all 7 sidebar sections programmatically, checking `at.exception` after each. Result: zero exceptions across the initial load and all 7 sections (Overview, Yield Intelligence, Risk Monitor, Explainability, What-if Simulator, Data Quality, Pipeline Health).
**Also verified directly** (before finding `AppTest`): every section's underlying pandas/model/SHAP/sqlite logic, extracted and run as plain Python outside Streamlit — including the untested-until-now combination of overriding all three what-if inputs (rainfall, temperature, pesticides) simultaneously, which produced a change of `-1.46e-11` hg/ha (floating-point noise, i.e. genuinely zero) — consistent with D13.1/D14.1's persistence-model finding holding even under a compound scenario.
**Why this belongs in the log**: "the server started" is a common, misleading proxy for "the UI works" with any framework that defers script execution past the initial HTTP response — worth naming the specific mechanism (WebSocket-gated execution) so this isn't mistaken for verification next time.

---

## D21.1 — Self-caught bug: a test that asserted the wrong module's contract

**Problem**: `test_merge_sources_does_not_fan_out` asserted that `merge_sources()` alone prevents row fan-out when given a weather source with duplicate `(area_key, year)` keys — it failed (4 rows instead of 2).
**Investigation**: the failure was correct behavior, not a regression — `merge_sources()` was never responsible for deduplication; that guarantee comes entirely from `clean_temp()`'s `groupby().mean()` step (D3.3). The test had assigned the fan-out-prevention contract to the wrong function.
**Fix**: split into two tests — `test_merge_sources_preserves_yield_row_count_given_deduplicated_inputs` (the real contract: no fan-out when inputs are already at `(area_key, year)` grain) and `test_merge_sources_fans_out_if_given_undeduplicated_input` (deliberately keeps proving the *absence* of protection at this layer, so if `merge_sources()` ever silently grows deduplication logic of its own, this test's docstring — describing where responsibility currently lives — is flagged as needing an update rather than the change going unnoticed).
**Why this is worth logging**: writing the test surfaced a real gap in how clearly the fan-out-prevention responsibility was documented across `clean_temp()` vs. `merge_sources()` — the roadmap's "implement → test → break → fix → document" loop caught a documentation/ownership ambiguity, not just a code bug, which is exactly what Phase 21 testing is supposed to do.

## D21.2 — `test_model_schema.py` skips (not fails) on a fresh checkout

The model input schema test needs `data/processed/yield_model.joblib`, a derived/gitignored artifact (D4.1's pattern) that doesn't exist until `python -m models.yield_model` has been run once. `pytestmark = pytest.mark.skipif(...)` makes this explicit and self-documenting in the test output, rather than either (a) failing confusingly on a fresh clone, or (b) silently committing a large binary model file to the repo just to make a test always runnable. Reproducibility note for the exit criteria ("the project can fail safely and predictably"): running `python -m pipeline.pipeline && python -m models.yield_model && python -m pytest` from a clean checkout exercises the full chain and turns this skip into a pass.

---

## D22.1 — Real bug: `streamlit run` doesn't put the project root on `sys.path`

**Problem**: `streamlit run dashboard/app.py` (the exact command in the README's own setup instructions) crashed immediately with `ModuleNotFoundError: No module named 'models'` on `from models.baseline import CUTOFF_YEAR` — reported directly from a real run, not caught by any check beforehand.
**Root cause**: every other script in this project is invoked as `python -m package.module` (`python -m models.yield_model`, etc.), which puts the project root on `sys.path` automatically. `streamlit run <file>` doesn't go through `-m` - Streamlit's script runner sets `sys.path[0]` to the *script's own directory* (`dashboard/`), so sibling top-level packages (`models/`, `features/`, `scenarios/`) aren't importable.
**Why Phase 20's AppTest verification (D20.1) didn't catch this**: `AppTest.from_file(...)` was invoked via `python -c "..."` from a shell already `cd`'d to the project root, so Python's own `sys.path` cwd-insertion papered over the exact gap the real `streamlit run` CLI hits. AppTest runs the script in-process; it doesn't reproduce the CLI's own path setup.
**Fix**: `dashboard/app.py` now inserts the project root onto `sys.path` explicitly, at the top of the file, before any project-internal import.
**Re-verification method, changed as a result**: fixed a real gap by adding a step AppTest structurally can't cover - launched the actual `streamlit run` server, opened a real headless-browser WebSocket session against it (Chrome DevTools Protocol), and confirmed both a clean server log and a correctly rendered page. AppTest remains useful for fast per-section exception checks; it is no longer treated as sufficient proof the CLI entrypoint itself works.

## D22.2 — Real bug: unconstrained region/crop defaults could show "no data" on first view

**Problem**: the Explainability and Yield Intelligence tabs each picked a region and a crop via two *independent* `st.selectbox` defaults (alphabetically-first, or a hardcoded region). Found visually, via the same real-browser screenshot used to verify D22.1: the Explainability tab's default landed on Afghanistan + Cassava, a (region, crop) pair with **zero** rows in the dataset, so a first-time viewer's first impression was "No data for this region/crop combination."
**Fix**: the crop dropdown's options are now derived from `df.loc[df["area"] == area, "crop"].unique()` - constrained to what that region actually grows - with the default index preferring "Maize" when available, matching the pattern the What-if Simulator tab already used correctly (its crop list was already filtered by the selected region). Applied to both the Yield Intelligence and Explainability sections.
**Why this matters more than it looks**: this is precisely the kind of default-state bug that a scripted test (AppTest, pytest) won't surface, because the "no data" branch is valid, handled code, not an exception — only actually looking at what renders catches it. Logged as a concrete instance of why the spec's "use the feature in a browser before reporting complete" instruction exists.

## D22.3 — Dashboard visual design pass (Phase 22 portfolio hardening)

Reworked `dashboard/app.py`'s presentation layer on top of the same, unchanged data logic: a custom theme (`.streamlit/config.toml` + injected CSS - Fraunces for headings, Public Sans for body, IBM Plex Mono for figures, a warm parchment/forest-green palette), unified matplotlib chart styling (replacing Streamlit's default `st.bar_chart` Vega-Lite theme with consistently-styled horizontal/diverging bar and scatter charts), top-level tab navigation instead of a sidebar radio, and a new "How it's built" tab that walks the 9-stage architecture and surfaces six of the decision log's most concrete self-caught bugs directly in the app - so a recruiter doesn't have to leave the dashboard to see the engineering judgment behind it. No data-loading or model logic changed; re-verified via AppTest (all tabs, zero exceptions) and a real browser session per D20.1/D22.1's method.
