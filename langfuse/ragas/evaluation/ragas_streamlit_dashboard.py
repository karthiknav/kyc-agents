from __future__ import annotations

import ast
import os
from typing import Any, List, Optional

import pandas as pd
import streamlit as st

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output"))

RAGAS_CSV = os.path.join(OUTPUT_DIR, "ragas_results.csv")
PIPELINE_CSV = os.path.join(OUTPUT_DIR, "pipeline_missing.csv")


# ----------------------------
# Helpers
# ----------------------------

def safe_load_csv(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        st.error(f"Failed loading CSV: {path}\n\n{e}")
        return None


def pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def is_empty_cell(v: Any) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return not str(v).strip()


def display_missing_artifacts(v: Any) -> str:
    if is_empty_cell(v):
        return "None"
    return str(v)


def parse_contexts(value: Any) -> List[str]:
    """
    ragas_results.csv often stores retrieved_contexts as a string that looks like:
      "['ctx1', 'ctx2', ...]"
    Use ast.literal_eval safely; fallback to raw.
    """
    if is_empty_cell(value):
        return []

    if isinstance(value, list):
        return [str(x) for x in value if x is not None and str(x).strip()]

    s = str(value).strip()
    try:
        parsed = ast.literal_eval(s)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x is not None and str(x).strip()]
    except Exception:
        pass
    return [s]


def mean_metric(df: pd.DataFrame, col: str) -> Optional[float]:
    if col not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce")
    m = s.mean()
    if pd.isna(m):
        return None
    return float(m)


# ----------------------------
# App config
# ----------------------------

st.set_page_config(page_title="KYC RAGAS Dashboard", layout="wide")
st.title("KYC Observability Dashboard (RAGAS + Pipeline)")

st.sidebar.write("Data directory:")
st.sidebar.code(OUTPUT_DIR)

ragas_df = safe_load_csv(RAGAS_CSV)
pipe_df = safe_load_csv(PIPELINE_CSV)

if pipe_df is None:
    st.error("pipeline_missing.csv not found. Run the batch evaluator first.")
    st.info(f"Expected at: {PIPELINE_CSV}")
    st.stop()

# ----------------------------
# Normalize pipeline df
# ----------------------------
if "case_id" not in pipe_df.columns:
    st.error("pipeline_missing.csv must contain column: case_id")
    st.stop()

# Make sure expected columns exist (so UI doesn't crash)
for c in ["missing_artifacts", "has_any_artifact", "has_all_artifacts"]:
    if c not in pipe_df.columns:
        pipe_df[c] = pd.NA

pipe_df["case_id"] = pipe_df["case_id"].astype(str)

# ----------------------------
# Normalize ragas df (optional)
# ----------------------------
if ragas_df is not None and not ragas_df.empty:
    if "case_id" not in ragas_df.columns:
        st.error("ragas_results.csv must contain column: case_id")
        st.stop()
    ragas_df["case_id"] = ragas_df["case_id"].astype(str)

    # Handle both schemas
    q_col = pick_col(ragas_df, ["question", "user_input"])
    a_col = pick_col(ragas_df, ["answer", "response"])
    c_col = pick_col(ragas_df, ["contexts", "retrieved_contexts"])

    if not q_col or not a_col or not c_col:
        st.error(
            "ragas_results.csv schema is not recognized.\n\n"
            f"Columns: {list(ragas_df.columns)}\n\n"
            "Expected one of:\n"
            "- question/answer/contexts\n"
            "- user_input/response/retrieved_contexts"
        )
        st.stop()

    # Rename to canonical names for UI
    ragas_view = ragas_df.rename(
        columns={q_col: "question", a_col: "answer", c_col: "contexts"}
    ).copy()
else:
    ragas_view = None

# ----------------------------
# Unified per-case view
# ----------------------------
# We always show pipeline cases; ragas metrics join when available.
if ragas_view is not None:
    # Prefer pipeline missing_artifacts (it is the source of truth for completeness)
    # Avoid "duplicate" missing artifacts by dropping from ragas if present.
    ragas_view = ragas_view.drop(columns=[c for c in ["missing_artifacts"] if c in ragas_view.columns], errors="ignore")

    merged = pipe_df.merge(ragas_view, on="case_id", how="left", suffixes=("", "_ragas"))
else:
    merged = pipe_df.copy()

# ----------------------------
# Tabs
# ----------------------------
tab1, tab2, tab3 = st.tabs(["Overview", "Case Detail", "Raw Tables"])

with tab1:
    st.subheader("Overview")

    total_cases = len(pipe_df)
    complete = int((pipe_df["has_all_artifacts"] == True).sum()) if "has_all_artifacts" in pipe_df.columns else 0  # noqa: E712
    missing_any = total_cases - complete

    c1, c2, c3 = st.columns(3)
    c1.metric("Total cases discovered", total_cases)
    c2.metric("Complete pipeline (all artifacts present)", complete)
    c3.metric("Missing artifacts (any)", missing_any)

    if ragas_view is not None:
        st.markdown("### RAGAS metric summary (evaluable cases)")
        m1 = mean_metric(ragas_view, "faithfulness")
        m2 = mean_metric(ragas_view, "answer_relevancy")

        d1, d2, d3 = st.columns(3)
        d1.metric("Evaluated cases", len(ragas_view))
        d2.metric("Avg Faithfulness", f"{m1:.3f}" if m1 is not None else "n/a")
        d3.metric("Avg Answer Relevancy", f"{m2:.3f}" if m2 is not None else "n/a")
    else:
        st.info("No ragas_results.csv found (or it is empty). You will only see pipeline completeness.")

    st.markdown("### Cases missing artifacts")
    missing_only = merged[merged["has_all_artifacts"] != True]  # noqa: E712
    if missing_only.empty:
        st.success("No missing artifacts detected.")
    else:
        show_cols = [c for c in ["case_id", "missing_artifacts", "has_any_artifact", "has_all_artifacts"] if c in missing_only.columns]
        st.dataframe(missing_only[show_cols], use_container_width=True)

with tab2:
    st.subheader("Case Detail")

    case_ids = list(merged["case_id"].dropna().astype(str).unique())
    if not case_ids:
        st.warning("No cases found.")
        st.stop()

    selected = st.selectbox("Select case", case_ids)
    row = merged[merged["case_id"] == str(selected)].iloc[0]

    st.markdown(f"### Case: `{selected}`")

    st.markdown("#### Pipeline completeness")
    st.write(f"Has all artifacts: `{row.get('has_all_artifacts')}`")
    st.write(f"Has any artifact: `{row.get('has_any_artifact')}`")
    st.write(f"Missing artifacts: **{display_missing_artifacts(row.get('missing_artifacts'))}**")

    if ragas_view is None or is_empty_cell(row.get("question")):
        st.info("This case was not evaluated by RAGAS (likely missing all artifacts or ragas_results.csv not present).")
    else:
        st.markdown("#### RAGAS evaluation inputs/outputs")
        st.write("**Faithfulness:**", row.get("faithfulness"))
        st.write("**Answer relevancy:**", row.get("answer_relevancy"))

        with st.expander("Question", expanded=True):
            st.write(row.get("question", ""))

        with st.expander("Answer", expanded=True):
            st.write(row.get("answer", ""))

        with st.expander("Contexts", expanded=False):
            ctxs = parse_contexts(row.get("contexts"))
            if not ctxs:
                st.write("(No contexts)")
            else:
                st.caption(f"{len(ctxs)} context item(s)")
                for i, c in enumerate(ctxs, start=1):
                    st.markdown(f"**Context {i}**")
                    st.text(c)
                    st.markdown("---")

with tab3:
    st.subheader("Raw tables")

    st.markdown("### pipeline_missing.csv")
    st.dataframe(pipe_df, use_container_width=True)

    st.markdown("### ragas_results.csv")
    if ragas_df is None:
        st.info("ragas_results.csv not found.")
    else:
        st.dataframe(ragas_df, use_container_width=True)

    st.markdown("### Joined view (pipeline + ragas)")
    st.dataframe(merged, use_container_width=True)
