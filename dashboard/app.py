"""Phase 20 - Streamlit dashboard: the decision-support layer everything
since Phase 0 has been building toward. Seven data sections (spec section 13)
plus an explanatory "How it's built" tab, each backed by real artifacts
already produced by earlier phases - nothing here is a placeholder number.

Concept: a dashboard is decision-oriented, not just "make some charts."
Each section answers one of the business questions from spec section 3 -
the section headers are literally those questions, not chart-type labels.
Presentation (fonts/palette/callouts) is custom-themed on top of Streamlit's
component model; every number and chart still comes from the same cached
loaders and model artifacts as the original build - see docs/decisions.md
D20.1/D22.1 for why the sys.path fix below exists.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# `streamlit run dashboard/app.py` sets sys.path[0] to this file's own
# directory (dashboard/), not the project root - unlike `python -m
# models.yield_model` etc. elsewhere in this project, which get the root
# on sys.path automatically via -m. Without this, `from models.baseline
# import ...` below fails with ModuleNotFoundError the moment the app is
# launched the normal way (`streamlit run dashboard/app.py`), even though
# it worked in Streamlit's AppTest harness during development - AppTest
# ran in-process from a shell already in the project root, which masked
# this (see docs/decisions.md D20.1/D22.1).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
import streamlit as st

from models.baseline import CUTOFF_YEAR
from models.evaluation import evaluate, temporal_split
from scenarios.what_if import DISCLAIMER, WhatIfEngine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_ROOT / "data" / "processed"
QUARANTINE = PROJECT_ROOT / "data" / "quarantine"

st.set_page_config(page_title="AgriPulse", layout="wide")

# ============================================================== theme ==
INK = "#1C1810"
INK_2 = "#5C5642"
INK_3 = "#8B8470"
BORDER = "#E1DDC9"
ACCENT = "#1a6b1a"
ACCENT_DARK = "#0f4a0f"
NEUTRAL = "#8B8470"
DIV_POS = "#2a78d6"
DIV_NEG = "#e34948"
GOOD = "#0ca30c"
WARNING = "#b5790a"
CRITICAL = "#d03b3b"

st.markdown(
    f"""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
      html, body, [class*="css"] {{ font-family: "Public Sans", -apple-system, "Segoe UI", sans-serif; }}
      h1, h2, h3 {{ font-family: "Fraunces", Georgia, serif !important; font-weight: 600 !important; letter-spacing: -0.01em; }}
      [data-testid="stMetricValue"] {{ font-family: "IBM Plex Mono", monospace; font-weight: 600; color: {INK}; }}
      [data-testid="stMetricLabel"] {{ font-size: 12px !important; text-transform: uppercase; letter-spacing: 0.04em; color: {INK_3} !important; }}
      [data-testid="stMetricDelta"] {{ font-family: "IBM Plex Mono", monospace; font-size: 12.5px; }}
      [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {BORDER}; }}
      [data-baseweb="tab"] {{ font-weight: 600; font-size: 14px; color: {INK_2}; }}
      [aria-selected="true"] {{ color: {ACCENT_DARK} !important; }}
      [data-testid="stVerticalBlockBorderWrapper"] > div {{ border-radius: 12px; }}
      .ap-eyebrow {{ font-family: "IBM Plex Mono", monospace; font-size: 12px; letter-spacing: 0.08em;
                      text-transform: uppercase; color: {ACCENT_DARK}; font-weight: 600; margin-bottom: 6px; }}
      .ap-hero-sub {{ color: {INK_2}; font-size: 16px; max-width: 74ch; line-height: 1.55; }}
      .ap-callout {{ background: rgba(26,107,26,0.08); border: 1px solid rgba(26,107,26,0.25);
                     border-radius: 10px; padding: 12px 16px; font-size: 13.5px; color: {INK_2}; margin: 10px 0; }}
      .ap-callout b, .ap-callout strong {{ color: {INK}; }}
      .ap-callout.warn {{ background: rgba(208,59,59,0.08); border-color: rgba(208,59,59,0.25); }}
      .ap-tag {{ display:inline-block; font-family:"IBM Plex Mono", monospace; font-size: 11px; font-weight: 600;
                 color: {ACCENT_DARK}; background: rgba(26,107,26,0.10); padding: 2px 8px; border-radius: 100px; margin-bottom: 6px; }}
      .ap-decision h4 {{ font-family:"Public Sans", sans-serif !important; font-size: 14.5px; font-weight: 700 !important;
                          margin: 2px 0 4px; color: {INK}; }}
      .ap-decision p {{ font-size: 13px; color: {INK_2}; margin: 0; line-height: 1.5; }}
    </style>
    """,
    unsafe_allow_html=True,
)

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10.5,
    "text.color": INK,
    "axes.edgecolor": BORDER,
    "axes.labelcolor": INK_2,
    "axes.grid": True,
    "grid.color": BORDER,
    "grid.linewidth": 0.7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "xtick.color": INK_3,
    "ytick.color": INK_3,
    "figure.facecolor": "none",
    "axes.facecolor": "none",
    "savefig.facecolor": "none",
})


def callout(text: str, warn: bool = False) -> None:
    cls = "ap-callout warn" if warn else "ap-callout"
    st.markdown(f'<div class="{cls}">{text}</div>', unsafe_allow_html=True)


def hbar(series: pd.Series, color: str = ACCENT, unit: str = "", figsize=(6, 3.2)):
    fig, ax = plt.subplots(figsize=figsize)
    series = series.sort_values()
    ax.barh(series.index.astype(str), series.values, color=color, height=0.62)
    ax.set_xlabel(unit)
    for spine in ("left",):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    return fig


def diverging_hbar(series: pd.Series, figsize=(6, 3.6)):
    fig, ax = plt.subplots(figsize=figsize)
    series = series.sort_values()
    colors = [DIV_POS if v >= 0 else DIV_NEG for v in series.values]
    ax.barh(series.index.astype(str), series.values, color=colors, height=0.62)
    ax.axvline(0, color=INK_3, linewidth=0.8)
    fig.tight_layout()
    return fig


def scatter_actual_pred(actual: np.ndarray, predicted: np.ndarray, figsize=(6, 6)):
    fig, ax = plt.subplots(figsize=figsize)
    ax.scatter(actual, predicted, alpha=0.15, s=12, color=DIV_POS, edgecolors="none")
    lims = [0, max(actual.max(), predicted.max())]
    ax.plot(lims, lims, color=CRITICAL, linewidth=1.2, linestyle="--", label="perfect prediction")
    ax.set_xlabel("Actual yield (hg/ha)")
    ax.set_ylabel("Predicted yield (hg/ha)")
    ax.legend(frameon=False, fontsize=9.5)
    fig.tight_layout()
    return fig


def sensitivity_line(multipliers, yields, figsize=(6, 3.6)):
    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(multipliers, yields, color=ACCENT, marker="o", markersize=4.5, linewidth=2)
    ax.axvline(1.0, color=INK_3, linewidth=0.8, linestyle=":")
    ax.set_ylim(0, max(yields) * 1.15)
    ax.set_xlabel("Rainfall multiplier (1.0 = actual historical value)")
    ax.set_ylabel("Predicted yield (hg/ha)")
    fig.tight_layout()
    return fig


# ---------- cached loaders (real artifacts from Phases 3-18, not mocks) ----------

@st.cache_data
def load_curated() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "curated_dataset.csv")


@st.cache_resource
def load_yield_artifact():
    return joblib.load(PROCESSED / "yield_model.joblib")


@st.cache_resource
def load_risk_artifact():
    return joblib.load(PROCESSED / "risk_model.joblib")


@st.cache_data
def load_quality_report() -> dict:
    path = QUARANTINE / "_quality_report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@st.cache_data
def load_pipeline_history(limit: int = 20) -> pd.DataFrame:
    db_path = PROCESSED / "monitoring.db"
    if not db_path.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df_hist = pd.read_sql_query(
        "SELECT * FROM pipeline_run ORDER BY started_at DESC LIMIT ?", conn, params=(limit,)
    )
    conn.close()
    return df_hist


@st.cache_data
def compute_test_predictions(_model_key: str):
    """y_true/y_pred on the held-out test set - used by both the
    "actual vs predicted" chart and the overview risk rate. _model_key is
    unused except to let Streamlit's cache key on something stable."""
    artifact = load_yield_artifact()
    model, fb = artifact["model"], artifact["feature_builder"]
    df_full = load_curated()
    _train_raw, test_raw = temporal_split(df_full, CUTOFF_YEAR)
    X_test = fb.transform(test_raw, df_full)
    y_pred = model.predict(X_test)
    return test_raw, X_test, y_pred


df = load_curated()
yield_artifact = load_yield_artifact()
yield_model, yield_fb = yield_artifact["model"], yield_artifact["feature_builder"]
risk_artifact = load_risk_artifact()
risk_model, risk_scaler, risk_thresholds = risk_artifact["model"], risk_artifact["scaler"], risk_artifact["risk_thresholds"]

# ============================================================== hero ==
st.markdown('<div class="ap-eyebrow">Data Science + Data Engineering portfolio project</div>', unsafe_allow_html=True)
st.title("AgriPulse")
st.markdown(
    '<p class="ap-hero-sub">Ingests 56 years of FAO/World Bank crop, weather, and pesticide data across '
    "212 regions, runs it through a real data-quality engine, and uses the result to predict yield, "
    "flag agricultural risk, and explain every prediction — honestly, including where the model is "
    "weaker than it looks. Every number below comes straight out of the pipeline; nothing is a mockup.</p>",
    unsafe_allow_html=True,
)

tabs = st.tabs([
    "Overview", "How it's built", "Yield Intelligence", "Risk Monitor",
    "Explainability", "What-if Simulator", "Data Quality", "Pipeline Health",
])

# ================================================================== Overview
with tabs[0]:
    test_raw, X_test, y_pred = compute_test_predictions("yield")
    risk_labels = (test_raw["yield_hg_ha"] < test_raw["crop"].map(risk_thresholds)).astype(int)
    history = load_pipeline_history(limit=1)

    with st.container(border=True):
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total records", f"{len(df):,}")
        c2.metric("Crops", df["crop"].nunique())
        c3.metric("Regions", df["area"].nunique())
        c4.metric("Avg. yield (hg/ha)", f"{df['yield_hg_ha'].mean():,.0f}")
        c5.metric("Risk rate (test period)", f"{risk_labels.mean():.1%}")
        c6.metric("Pipeline", history.iloc[0]["status"] if not history.empty else "no runs yet")

    st.subheader("Average yield by decade")
    decade = (df["year"] // 10) * 10
    fig = hbar(df.groupby(decade)["yield_hg_ha"].mean(), color=ACCENT, figsize=(9, 3))
    st.pyplot(fig, clear_figure=True)

    callout(
        "<b>Risk rate</b> uses the crop-relative underperformance definition from Phase 10 (D10.1) — "
        "yield below that crop's own 25th percentile, with thresholds fit on training data only, "
        "never on the years being scored."
    )

# ============================================================== How it's built
with tabs[1]:
    st.subheader("Nine stages, each a real module in this repo")
    st.markdown(
        "Bad records get quarantined with a reason code — never silently dropped — and the transform "
        "stage doesn't run until the quality gate has actually cleared the data."
    )

    stages = [
        ("01", "Sources", "FAO / World Bank CSVs — yield, pesticides, rainfall, temperature"),
        ("02", "Ingestion", "Validate, copy into the raw data lake, log a run manifest"),
        ("03", "Raw lake", "Untouched copies — kept even if wrong, for debugging"),
        ("04", "Quality", "Schema + business-rule checks, per source"),
        ("05", "Quarantine", "Rejected rows, reason-coded — never deleted"),
        ("06", "Transform", "Clean, join, dedupe — pandas (or Spark, measured — see below)"),
        ("07", "Curated + SQL", "Model-ready table, normalized into 5 SQL tables"),
        ("08", "ML + SHAP", "Yield, risk, clustering models — explained, not just scored"),
        ("09", "Decision layer", "This dashboard, the what-if simulator, monitoring"),
    ]
    cols = st.columns(len(stages))
    for col, (num, title, desc) in zip(cols, stages):
        with col:
            with st.container(border=True):
                st.markdown(f'<span class="ap-tag">{num}</span>', unsafe_allow_html=True)
                st.markdown(f"**{title}**")
                st.caption(desc)

    callout(
        "<b>Why this order matters:</b> until Phase 15, the transform step quietly read straight from "
        "raw files, bypassing the quality gate entirely — a real gap found by re-reading the architecture "
        "against the code, not by a test failing. Fixing it dropped the curated dataset by exactly 9 rows: "
        "the 9 records quality had been catching all along. See decision <b>D15.1</b>."
    )

    st.subheader("The bugs we caught, and what they taught us")
    st.caption("A selection from the 54-entry decision log — every one is a real mistake, found and fixed during development.")

    decisions = [
        ("D3.3", "A join that looked fine, wasn't",
         "The curated dataset came out at 121,936 rows — more than double the 56,717-row source table. "
         "The cause: temp.csv is sub-annual, not one row per country-year, so the merge fanned out. "
         "Caught by a row-count sanity check, not an error message."),
        ("D13.1", "The model is a persistence model",
         "SHAP and permutation importance agree: last year's yield explains ~98% of the model's "
         "predictions. Weather and pesticide use barely register. Reported honestly instead of "
         "overselling the model as “weather-driven.”"),
        ("D16.1", "Measured, not assumed: pandas beat Spark here",
         "Same transform, both engines: pandas ran in 0.78s, Spark took 34.0s — almost all of it JVM "
         "startup and query planning. Spark stays in the repo to demonstrate it, not to replace the "
         "real pipeline."),
        ("D20.1", "“HTTP 200” isn't proof a Streamlit app runs",
         "curl returned 200 while the app was silently crashing on every real session — Streamlit "
         "defers script execution until a browser opens a WebSocket. Caught with Streamlit's own "
         "AppTest framework, not a browser."),
        ("D21.1", "A test that blamed the wrong function",
         "A test asserted duplicate-row protection was merge_sources()'s job. It failed — because "
         "that protection actually lives in clean_temp(). The fix was rewriting the test's contract, "
         "not the code."),
        ("D5.1", "“Old” isn't the same as “invalid”",
         "An early data-quality rule rejected 31,981 genuine pre-1900 temperature readings as "
         "out-of-range. They were real historical records, older than the yield data's own window — "
         "a scoping question, not a validity one."),
    ]
    dcols = st.columns(2)
    for i, (tag, title, body) in enumerate(decisions):
        with dcols[i % 2]:
            with st.container(border=True):
                st.markdown(
                    f'<div class="ap-decision"><span class="ap-tag">{tag}</span>'
                    f"<h4>{title}</h4><p>{body}</p></div>",
                    unsafe_allow_html=True,
                )

    st.caption("Full log: `docs/decisions.md` in the repo — 54 entries across all phases.")

# ========================================================= Yield Intelligence
with tabs[2]:
    test_raw, X_test, y_pred = compute_test_predictions("yield")

    st.subheader("Predict yield for a region / crop / year")
    col1, col2 = st.columns(2)
    with col1:
        area = st.selectbox("Region", sorted(df["area"].unique()), index=sorted(df["area"].unique()).index("India") if "India" in df["area"].values else 0)
    with col2:
        # Crop options are constrained to what this region actually grows -
        # an unconstrained list let the default selection land on a
        # nonexistent (region, crop) pair (e.g. Afghanistan+Cassava),
        # showing "no data" as the first thing a viewer saw. Same fix
        # applied to the Explainability SHAP picker below.
        crops_for_area = sorted(df.loc[df["area"] == area, "crop"].unique())
        crop = st.selectbox("Crop", crops_for_area, index=crops_for_area.index("Maize") if "Maize" in crops_for_area else 0)
    available_years = sorted(df.loc[(df["area"] == area) & (df["crop"] == crop), "year"].unique())
    if available_years:
        year = st.select_slider("Year", options=available_years, value=available_years[-1])
        row = df[(df["area"] == area) & (df["crop"] == crop) & (df["year"] == year)].iloc[[0]]
        features = yield_fb.transform(row, df)
        pred = yield_model.predict(features)[0]
        actual = row["yield_hg_ha"].iloc[0]
        with st.container(border=True):
            m1, m2 = st.columns(2)
            m1.metric("Predicted yield (hg/ha)", f"{pred:,.0f}")
            m2.metric("Actual yield (hg/ha)", f"{actual:,.0f}", delta=f"{pred - actual:+,.0f} predicted − actual")
    else:
        st.info("No data for this region/crop combination.")

    st.divider()
    st.subheader("The baseline isn't a strawman")
    st.caption(
        "The baseline is “this region and crop's own historical mean,” which already explains "
        "72% of the variance — every model has to earn its keep on top of that, not against a global average."
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Actual vs. predicted yield**")
        st.caption("Test set: 2005–2016, held out by year, never shuffled into training.")
        fig = scatter_actual_pred(test_raw["yield_hg_ha"].to_numpy(), y_pred)
        st.pyplot(fig, clear_figure=True)
        metrics = evaluate(test_raw["yield_hg_ha"].to_numpy(), y_pred)
        st.caption(f"Random Forest — MAE={metrics.mae:,.0f}, RMSE={metrics.rmse:,.0f}, R²={metrics.r2:.4f}")
    with col_b:
        st.markdown("**Average yield by crop**")
        st.caption("Root/tuber crops read far higher — that's harvest-weight (fresh vs. dry), not a fairer farm. See D7.3.")
        fig = hbar(df.groupby("crop")["yield_hg_ha"].mean(), color=ACCENT, figsize=(6, 4.2))
        st.pyplot(fig, clear_figure=True)

    st.markdown("**Regional performance, standardized within crop**")
    st.caption("Z-score vs. that crop's own mean — comparable across crops, unlike raw yield.")
    grouped = df.groupby("crop")["yield_hg_ha"]
    z = (df["yield_hg_ha"] - grouped.transform("mean")) / grouped.transform("std")
    region_z = z.groupby(df["area"]).mean().sort_values(ascending=False)
    top_bottom = pd.concat([region_z.head(8), region_z.tail(5)])
    fig = diverging_hbar(top_bottom, figsize=(9, 4.2))
    st.pyplot(fig, clear_figure=True)

# =============================================================== Risk Monitor
with tabs[3]:
    test_raw, X_test, y_pred = compute_test_predictions("yield")
    risk_labels = (test_raw["yield_hg_ha"] < test_raw["crop"].map(risk_thresholds)).astype(int)

    st.subheader('Why "94% accurate" can still be a bad model')
    st.caption(
        '"High risk" means this region/crop/year underperformed that crop’s own 25th percentile — '
        "a real, data-grounded definition, not an invented drought or disease label the data can't support."
    )

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("Overall risk score (test period)", f"{risk_labels.mean():.1%}")
        c2.metric("High-risk observations", f"{risk_labels.sum():,} / {len(risk_labels):,}")
        c3.metric("Class balance in training data", "25.0%")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Risk distribution**")
        fig = hbar(risk_labels.value_counts().rename({0: "low_risk", 1: "high_risk"}), color=ACCENT, figsize=(6, 2.4))
        st.pyplot(fig, clear_figure=True)
    with col_b:
        st.markdown("**Highest-risk regions**")
        st.caption("Share of observations flagged high-risk (min. 5 observations).")
        region_risk = risk_labels.groupby(test_raw["area"]).mean().sort_values(ascending=False)
        region_counts = test_raw.groupby("area").size()
        region_table = pd.DataFrame({"risk_rate": region_risk, "n_observations": region_counts}).query("n_observations >= 5")
        st.dataframe(region_table.sort_values("risk_rate", ascending=False).head(10), width="stretch")

    callout(
        "<b>Risk</b> = crop-relative yield underperformance (Phase 10, D10.1), <b>not</b> a drought/disease "
        "diagnosis — this dataset has no drought or disease information to support that label.",
        warn=True,
    )

# ================================================================= Explainability
with tabs[4]:
    st.subheader("What the model actually weighs")
    st.caption(
        "Every bar below says what the model leaned on for a prediction — never that a factor "
        '"caused" a real-world outcome. This dataset is correlational; SHAP explains the model, not the field.'
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Global feature importance**")
        st.caption("Impurity-based, Random Forest.")
        importances = pd.Series(yield_model.feature_importances_, index=yield_fb.transform(df.iloc[[0]], df).columns).sort_values(ascending=False)
        fig = hbar(importances.head(8), color=ACCENT, figsize=(6, 4))
        st.pyplot(fig, clear_figure=True)
        callout(
            f"<b>{importances.index[0]}</b> alone accounts for <b>{importances.iloc[0] / importances.sum():.1%}</b> "
            "of total importance — this model is overwhelmingly a persistence model (predicting from last "
            "year's yield), not a rich weather-driven one. See D13.1."
        )
    with col_b:
        st.markdown("**One real prediction, explained**")
        c1, c2, c3 = st.columns(3)
        with c1:
            areas = sorted(df["area"].unique())
            shap_area = st.selectbox("Region", areas, index=areas.index("India") if "India" in areas else 0, key="shap_area")
        with c2:
            shap_crops_for_area = sorted(df.loc[df["area"] == shap_area, "crop"].unique())
            shap_crop = st.selectbox("Crop", shap_crops_for_area, index=shap_crops_for_area.index("Maize") if "Maize" in shap_crops_for_area else 0, key="shap_crop")
        shap_years = sorted(df.loc[(df["area"] == shap_area) & (df["crop"] == shap_crop), "year"].unique())
        if shap_years:
            with c3:
                shap_year = st.select_slider("Year", options=shap_years, value=shap_years[-1], key="shap_year")
            row = df[(df["area"] == shap_area) & (df["crop"] == shap_crop) & (df["year"] == shap_year)].iloc[[0]]
            features = yield_fb.transform(row, df)
            explainer = shap.TreeExplainer(yield_model)
            shap_values = explainer(features)
            contributions = pd.Series(shap_values.values[0], index=features.columns).sort_values(key=abs, ascending=False)

            st.metric("Predicted yield (hg/ha)", f"{yield_model.predict(features)[0]:,.0f}")
            fig = diverging_hbar(contributions.head(6), figsize=(6, 3.4))
            st.pyplot(fig, clear_figure=True)
            st.caption("Blue = pushed prediction up. Red = pushed it down. Associated with, not caused by.")
        else:
            st.info("No data for this region/crop combination.")

# ============================================================ What-if Simulator
with tabs[5]:
    st.subheader("Change the weather, watch the prediction barely move")
    callout(DISCLAIMER, warn=True)

    engine = WhatIfEngine(yield_model, yield_fb, df)
    complete = df.dropna(subset=["rainfall_mm", "avg_temp_c", "pesticides_tonnes"])

    col1, col2, col3 = st.columns(3)
    with col1:
        wi_area = st.selectbox("Region", sorted(complete["area"].unique()), key="wi_area")
    with col2:
        available_crops = sorted(complete.loc[complete["area"] == wi_area, "crop"].unique())
        wi_crop = st.selectbox("Crop", available_crops, key="wi_crop")
    wi_years = sorted(complete.loc[(complete["area"] == wi_area) & (complete["crop"] == wi_crop), "year"].unique())
    with col3:
        wi_year = st.select_slider("Year", options=wi_years, value=wi_years[-1], key="wi_year") if wi_years else None

    if wi_year:
        base_row = df[(df["area"] == wi_area) & (df["crop"] == wi_crop) & (df["year"] == wi_year)].iloc[0]
        st.caption(f"Baseline: rainfall={base_row['rainfall_mm']:.0f}mm, temp={base_row['avg_temp_c']:.1f}°C, pesticides={base_row['pesticides_tonnes']:.1f}t")

        c1, c2, c3 = st.columns(3)
        rainfall = c1.slider("Rainfall (mm/year)", 0.0, float(base_row["rainfall_mm"] * 2), float(base_row["rainfall_mm"]))
        temp = c2.slider("Avg temperature (°C)", -10.0, 45.0, float(base_row["avg_temp_c"]))
        pesticides = c3.slider("Pesticide use (tonnes)", 0.0, float(max(base_row["pesticides_tonnes"] * 2, 100)), float(base_row["pesticides_tonnes"]))

        result = engine.scenario(wi_area, wi_crop, int(wi_year), {"rainfall_mm": rainfall, "avg_temp_c": temp, "pesticides_tonnes": pesticides})

        with st.container(border=True):
            m1, m2, m3 = st.columns(3)
            m1.metric("Baseline prediction", f"{result['baseline_prediction_hg_ha']:,.0f} hg/ha")
            m2.metric("Scenario prediction", f"{result['scenario_prediction_hg_ha']:,.0f} hg/ha", delta=f"{result['absolute_change_hg_ha']:+,.0f}")
            m3.metric("Percent change", f"{result['percent_change']:+.2f}%")

        st.markdown("**Sensitivity to rainfall alone**")
        st.caption("Same region/crop/year, rainfall scaled 0.5×–1.5×, everything else held fixed.")
        sensitivity = engine.sensitivity_analysis(wi_area, wi_crop, int(wi_year), "rainfall_mm", np.linspace(0.5, 1.5, 11))
        fig = sensitivity_line(sensitivity["multiplier"], sensitivity["predicted_yield_hg_ha"])
        st.pyplot(fig, clear_figure=True)
        spread = sensitivity["predicted_yield_hg_ha"].max() - sensitivity["predicted_yield_hg_ha"].min()
        callout(
            f"Full 0.5×–1.5× rainfall range moves the prediction by only "
            f"<b>{spread:,.0f} hg/ha</b> — consistent with the explainability finding that this model "
            "leans on last year's yield far more than on weather. See D13.1/D14.1."
        )

# ================================================================= Data Quality
with tabs[6]:
    st.subheader("What got rejected, and why")
    st.caption(
        "Every rejected record is quarantined with a machine-readable reason — never silently dropped. "
        "A 95% quality score means the other 5% is fully accounted for, not missing."
    )
    report = load_quality_report()
    if not report:
        st.info("No quality report found - run `python -m quality.quality_report` first.")
    else:
        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            c1.metric("Overall quality score", f"{report['overall_quality_score_pct']}%")
            c2.metric("Total records", f"{report['overall_total_records']:,}")
            c3.metric("Rejected records", f"{report['overall_rejected_records']:,}")

        st.markdown("**Per-source quality**")
        per_source = pd.DataFrame(report["per_source"]).T[["total_records", "accepted_records", "rejected_records", "quality_score_pct", "validation_status"]]
        st.dataframe(per_source, width="stretch")

        st.markdown("**Rejection reasons**")
        for name, r in report["per_source"].items():
            if r["rejection_reason_counts"]:
                st.write(f"**{name}**: {r['rejection_reason_counts']}")

# =============================================================== Pipeline Health
with tabs[7]:
    st.subheader("Every run, including the one we broke on purpose")
    st.caption(
        "A monitoring database that survives pipeline reruns, tracking status, duration, and record "
        "counts per run — with a real induced-failure test kept in the history to prove failures are "
        "diagnosable, not just theoretically loggable."
    )
    history = load_pipeline_history(limit=20)
    if history.empty:
        st.info("No pipeline runs recorded yet — run `python -m monitoring.pipeline_monitor` first.")
    else:
        latest = history.iloc[0]
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Latest run status", latest["status"])
            c2.metric("Duration", f"{latest['duration_sec']:.2f}s")
            c3.metric("Curated rows", f"{latest['curated_rows']}" if pd.notna(latest["curated_rows"]) else "n/a")
            c4.metric("Quality score", f"{latest['overall_quality_score_pct']}%" if pd.notna(latest["overall_quality_score_pct"]) else "n/a")

        st.markdown("**Recent runs**")
        st.dataframe(history[["started_at", "status", "duration_sec", "records_received", "records_accepted", "records_rejected", "overall_quality_score_pct"]], width="stretch")

        failures = history[history["status"] == "FAILED"]
        if not failures.empty:
            st.markdown(f"**{len(failures)} failed run(s) in history**")
            for _, frow in failures.iterrows():
                with st.expander(f"{frow['started_at']} — {frow['error_message'].splitlines()[0] if frow['error_message'] else 'unknown error'}"):
                    st.code(frow["error_message"])
