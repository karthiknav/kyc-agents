"""
XGBoost training script for the KYC risk scorer.

SageMaker passes data via SM_CHANNEL_* env vars and model output via SM_MODEL_DIR.
The training CSV has no header; col 0 is the label (0=low, 1=medium, 2=high).

Hyper-parameters are forwarded from the SageMaker Estimator:
  max-depth, eta, num-round, subsample, colsample-bytree,
  min-child-weight, early-stopping-rounds
"""

import argparse
import json
import logging
import os

import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, roc_auc_score
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_dmatrix(directory: str) -> xgb.DMatrix:
    files = [f for f in os.listdir(directory) if f.endswith(".csv")]
    frames = [pd.read_csv(os.path.join(directory, f), header=None) for f in files]
    df = pd.concat(frames, ignore_index=True)
    X = df.iloc[:, 1:].values
    y = df.iloc[:, 0].values.astype(int)
    return xgb.DMatrix(X, label=y)


def main() -> None:
    parser = argparse.ArgumentParser()

    # Hyper-parameters (forwarded by SageMaker Estimator as CLI args)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--eta", type=float, default=0.1)
    parser.add_argument("--num-round", type=int, default=150)
    parser.add_argument("--subsample", type=float, default=0.8)
    parser.add_argument("--colsample-bytree", type=float, default=0.8)
    parser.add_argument("--min-child-weight", type=int, default=5)
    parser.add_argument("--early-stopping-rounds", type=int, default=15)

    # SageMaker-injected paths
    parser.add_argument("--model-dir", type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    parser.add_argument("--train", type=str, default=os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train"))
    parser.add_argument("--validation", type=str, default=os.environ.get("SM_CHANNEL_VALIDATION", "/opt/ml/input/data/validation"))
    args = parser.parse_args()

    logger.info("Loading training data from %s", args.train)
    dtrain = _load_dmatrix(args.train)
    logger.info("Train size: %d rows", dtrain.num_row())

    evals = [(dtrain, "train")]
    dval = None
    if os.path.isdir(args.validation) and os.listdir(args.validation):
        logger.info("Loading validation data from %s", args.validation)
        dval = _load_dmatrix(args.validation)
        evals.append((dval, "validation"))
        logger.info("Validation size: %d rows", dval.num_row())

    params = {
        "objective": "multi:softprob",
        "num_class": 3,
        "max_depth": args.max_depth,
        "eta": args.eta,
        "subsample": args.subsample,
        "colsample_bytree": args.colsample_bytree,
        "min_child_weight": args.min_child_weight,
        "eval_metric": ["mlogloss", "merror"],
        "seed": 42,
        "verbosity": 1,
    }

    model = xgb.train(
        params,
        dtrain,
        num_boost_round=args.num_round,
        evals=evals,
        early_stopping_rounds=args.early_stopping_rounds if dval else None,
        verbose_eval=10,
    )

    logger.info("Best iteration: %d", model.best_iteration)

    # Quick train-set AUC for logging
    y_train = dtrain.get_label().astype(int)
    proba = model.predict(dtrain).reshape(-1, 3)
    auc = roc_auc_score(y_train, proba, multi_class="ovr", average="macro")
    logger.info("Train AUC (macro OVR): %.4f", auc)

    os.makedirs(args.model_dir, exist_ok=True)
    model_path = os.path.join(args.model_dir, "xgboost-model")
    model.save_model(model_path)
    logger.info("Model saved → %s", model_path)

    # Write feature names for documentation (picked up by evaluate.py)
    meta = {
        "feature_names": [
            "pep_match_score", "sanctions_hit", "doc_authenticity_score",
            "adverse_media_hits", "adverse_media_severity",
            "pep_match_type", "doc_status", "country_risk_tier",
        ],
        "label_map": {"0": "low", "1": "medium", "2": "high"},
        "best_iteration": model.best_iteration,
        "train_auc_macro_ovr": round(auc, 4),
    }
    with open(os.path.join(args.model_dir, "model_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


if __name__ == "__main__":
    main()
