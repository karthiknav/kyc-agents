"""
Preprocessing script for the KYC risk scorer.

Input  (channel 'input'): raw training CSV with headers.
Output (channels 'train', 'test'): headerless CSVs, label first column.

Expected input columns
----------------------
customer_id, pep_match_score, pep_match_type, sanctions_hit, doc_status,
doc_authenticity_score, adverse_media_hits, adverse_media_severity,
country_risk_tier, final_risk_label
(plus optional: event_time, confirmed_by, confirmed_at)

Encoding
--------
- pep_match_type      : none=0  fuzzy=1  exact=2
- doc_status          : failed=0  unreadable=1  verified=2
- adverse_media_sev   : none=0  low=1  medium=2  high=3  critical=4
  (already numeric values are passed through unchanged)
- country_risk_tier   : low=1  medium=2  high=3  very_high=4  critical=5
  (already numeric values 1-5 are passed through)
- final_risk_label    : low=0  medium=1  high=2  rejected→2

Output column order (no header)
--------------------------------
col 0 : final_risk_label  ← XGBoost label-first convention
col 1 : pep_match_score
col 2 : sanctions_hit
col 3 : doc_authenticity_score
col 4 : adverse_media_hits
col 5 : adverse_media_severity
col 6 : pep_match_type
col 7 : doc_status
col 8 : country_risk_tier
"""

import argparse
import os

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

# ── Encoding maps ────────────────────────────────────────────────────────────

PEP_MATCH_TYPE_MAP = {"none": 0, "fuzzy": 1, "exact": 2}
DOC_STATUS_MAP = {"failed": 0, "unreadable": 1, "verified": 2}
ADVERSE_SEVERITY_MAP = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
COUNTRY_RISK_MAP = {"low": 1, "medium": 2, "high": 3, "very_high": 4, "critical": 5}
LABEL_MAP = {"low": 0, "medium": 1, "high": 2, "rejected": 2}

DROP_COLS = ["customer_id", "event_time", "confirmed_by", "confirmed_at"]

NUMERIC_FEATURES = [
    "pep_match_score",
    "sanctions_hit",
    "doc_authenticity_score",
    "adverse_media_hits",
    "adverse_media_severity",
]
CATEGORICAL_FEATURES = [
    "pep_match_type",
    "doc_status",
    "country_risk_tier",
]
LABEL_COL = "final_risk_label"
FEATURE_ORDER = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _encode_ordinal(series: pd.Series, mapping: dict, default: int) -> pd.Series:
    """Map string values with a dict; pass through ints/floats unchanged."""
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(default).astype(int)
    return series.str.lower().map(mapping).fillna(default).astype(int)


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    drop = [c for c in DROP_COLS if c in df.columns]
    df = df.drop(columns=drop)

    df["pep_match_type"] = _encode_ordinal(df["pep_match_type"], PEP_MATCH_TYPE_MAP, 0)
    df["doc_status"] = _encode_ordinal(df["doc_status"], DOC_STATUS_MAP, 0)
    df["adverse_media_severity"] = _encode_ordinal(df["adverse_media_severity"], ADVERSE_SEVERITY_MAP, 0)
    df["country_risk_tier"] = _encode_ordinal(df["country_risk_tier"], COUNTRY_RISK_MAP, 2)

    df["pep_match_score"] = df["pep_match_score"].clip(0, 100).fillna(0)
    df["doc_authenticity_score"] = df["doc_authenticity_score"].clip(0, 100).fillna(0)
    df["adverse_media_hits"] = df["adverse_media_hits"].clip(0, 50).fillna(0)
    df["sanctions_hit"] = df["sanctions_hit"].fillna(0).astype(int)

    df[LABEL_COL] = df[LABEL_COL].str.lower().map(LABEL_MAP)
    df = df.dropna(subset=[LABEL_COL])
    df[LABEL_COL] = df[LABEL_COL].astype(int)

    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-data", type=str, default="/opt/ml/processing/input")
    parser.add_argument("--output-train", type=str, default="/opt/ml/processing/output/train")
    parser.add_argument("--output-test", type=str, default="/opt/ml/processing/output/test")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-seed", type=int, default=42)
    args = parser.parse_args()

    csv_files = [f for f in os.listdir(args.input_data) if f.endswith(".csv")]
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {args.input_data}")

    df = pd.concat(
        [pd.read_csv(os.path.join(args.input_data, f)) for f in csv_files],
        ignore_index=True,
    )
    print(f"Loaded {len(df)} rows | columns: {list(df.columns)}")

    df = preprocess(df)
    print(f"After encoding: {len(df)} rows | label distribution:\n{df[LABEL_COL].value_counts().to_dict()}")

    X = df[FEATURE_ORDER]
    y = df[LABEL_COL]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=args.test_size,
        random_state=args.random_seed,
        stratify=y,
    )

    # Label as first column — XGBoost convention; no header for built-in CSV loader
    train_out = pd.concat([y_train.reset_index(drop=True), X_train.reset_index(drop=True)], axis=1)
    test_out = pd.concat([y_test.reset_index(drop=True), X_test.reset_index(drop=True)], axis=1)

    os.makedirs(args.output_train, exist_ok=True)
    os.makedirs(args.output_test, exist_ok=True)

    train_path = os.path.join(args.output_train, "train.csv")
    test_path = os.path.join(args.output_test, "test.csv")

    train_out.to_csv(train_path, index=False, header=False)
    test_out.to_csv(test_path, index=False, header=False)

    print(f"Wrote {len(train_out)} train rows → {train_path}")
    print(f"Wrote {len(test_out)} test rows  → {test_path}")


if __name__ == "__main__":
    main()
