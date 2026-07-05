"""
Model evaluation script — runs inside a SKLearnProcessor job.

Reads the model artifact (model.tar.gz) and the test CSV,
produces evaluation.json with AUC, accuracy, and per-class metrics.
The pipeline's ConditionStep reads metrics.auc_macro_ovr.value to
decide whether to register the model.

xgboost is not in the SKLearnProcessor base image, so we install it here.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tarfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Install xgboost into the sklearn container at runtime
subprocess.run([sys.executable, "-m", "pip", "install", "xgboost>=1.7.0", "--quiet"], check=True)

import numpy as np  # noqa: E402 (after pip install)
import pandas as pd  # noqa: E402
import xgboost as xgb  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    accuracy_score,
    classification_report,
    confusion_matrix,
    roc_auc_score,
)

LABEL_NAMES = ["low", "medium", "high"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=str, default="/opt/ml/processing/input/model")
    parser.add_argument("--test-dir", type=str, default="/opt/ml/processing/input/test")
    parser.add_argument("--output-dir", type=str, default="/opt/ml/processing/evaluation")
    args = parser.parse_args()

    # ── Extract model ────────────────────────────────────────────────────────
    model_tar = os.path.join(args.model_dir, "model.tar.gz")
    extract_dir = "/tmp/model_extract"
    os.makedirs(extract_dir, exist_ok=True)
    with tarfile.open(model_tar, "r:gz") as tar:
        tar.extractall(extract_dir)

    model = xgb.Booster()
    model.load_model(os.path.join(extract_dir, "xgboost-model"))
    logger.info("Model loaded from %s", extract_dir)

    # ── Load test data ────────────────────────────────────────────────────────
    test_files = [f for f in os.listdir(args.test_dir) if f.endswith(".csv")]
    df = pd.concat(
        [pd.read_csv(os.path.join(args.test_dir, f), header=None) for f in test_files],
        ignore_index=True,
    )
    X_test = df.iloc[:, 1:].values
    y_test = df.iloc[:, 0].values.astype(int)
    logger.info("Test size: %d rows", len(y_test))

    # ── Predict ───────────────────────────────────────────────────────────────
    dtest = xgb.DMatrix(X_test)
    proba = model.predict(dtest).reshape(-1, 3)
    y_pred = np.argmax(proba, axis=1)

    # ── Metrics ───────────────────────────────────────────────────────────────
    auc = roc_auc_score(y_test, proba, multi_class="ovr", average="macro")
    accuracy = accuracy_score(y_test, y_pred)
    report = classification_report(y_test, y_pred, target_names=LABEL_NAMES, output_dict=True)
    cm = confusion_matrix(y_test, y_pred).tolist()

    evaluation = {
        "metrics": {
            "auc_macro_ovr": {"value": round(float(auc), 4), "standard_deviation": "NaN"},
            "accuracy": {"value": round(float(accuracy), 4), "standard_deviation": "NaN"},
        },
        "per_class": {
            label: {
                "precision": round(report[label]["precision"], 4),
                "recall": round(report[label]["recall"], 4),
                "f1": round(report[label]["f1-score"], 4),
                "support": int(report[label]["support"]),
            }
            for label in LABEL_NAMES
            if label in report
        },
        "confusion_matrix": {"labels": LABEL_NAMES, "values": cm},
    }

    logger.info("AUC (macro OVR): %.4f", auc)
    logger.info("Accuracy:        %.4f", accuracy)
    for label in LABEL_NAMES:
        if label in evaluation["per_class"]:
            p = evaluation["per_class"][label]
            logger.info("  %-10s  precision=%.3f  recall=%.3f  f1=%.3f  support=%d",
                        label, p["precision"], p["recall"], p["f1"], p["support"])

    os.makedirs(args.output_dir, exist_ok=True)
    eval_path = os.path.join(args.output_dir, "evaluation.json")
    with open(eval_path, "w") as f:
        json.dump(evaluation, f, indent=2)
    logger.info("Evaluation report → %s", eval_path)


if __name__ == "__main__":
    main()
