# KYC Risk Scorer — SageMaker ML Module

This module trains a machine learning model that predicts how risky a KYC case is — **low**, **medium**, or **high** — based on signals from the screening pipeline. It runs entirely on AWS SageMaker.

---

## ML Concepts (new to ML? start here)

### What is a "model"?
A model is a mathematical function that maps inputs (features) to outputs (predictions). Here, you give it 8 numbers describing a KYC case and it outputs a risk tier. Training is the process of adjusting the model's internal parameters by showing it thousands of labelled examples until it gets good at the task.

### Features and labels
- **Features** — the inputs. The 8 signals derived from a KYC case (PEP score, document status, etc.).
- **Label** — the answer you want to predict. Here: `low`, `medium`, or `high` risk.
- **Training data** — a CSV of past cases where a human compliance officer confirmed the correct label.

### Train / test split
You never evaluate a model on data it trained on — that would be cheating. So the dataset is split:
- **80% train** — the model learns from this.
- **20% test** — held back and used only to measure how well the model performs on unseen cases.

### XGBoost
[XGBoost](https://xgboost.readthedocs.io/) is a **gradient-boosted decision tree** algorithm. Think of it as an ensemble of many small "if-then" trees that vote together. It is the standard choice for structured/tabular data (rows + columns) because it:
- Handles mixed feature types (numbers, ordinal categories) well
- Is fast to train
- Generalises well with relatively little data
- Is interpretable (you can see feature importance)

The model here uses `multi:softprob` — a multi-class variant that outputs a probability for each of the three risk classes, not just a single answer.

### scikit-learn (sklearn)
[scikit-learn](https://scikit-learn.org/) is Python's standard ML toolkit. This project uses it for:
- `train_test_split` — splitting data reproducibly
- `roc_auc_score`, `accuracy_score`, `classification_report` — measuring model quality

### AUC (Area Under the ROC Curve)
AUC is the primary quality gate used in this pipeline.

#### Step 1 — The model outputs a probability, not a yes/no

The model doesn't say "this case is high risk". It says "this case is 82% likely to be high risk". You then choose a **threshold** to turn that probability into a decision:
- Threshold 0.5 → flag anything above 50% as high risk
- Threshold 0.8 → only flag if you're very confident

The "right" threshold depends on your priorities. A strict compliance team might set it low (catch everything, even at the cost of more false alarms). A lenient one might set it high (only flag the obvious cases).

#### Step 2 — The ROC curve shows every possible threshold at once

At each threshold, you can measure two things:
- **True Positive Rate (TPR / Recall)** — of all the truly high-risk cases, what fraction did we flag? Higher is better.
- **False Positive Rate (FPR)** — of all the truly low-risk cases, what fraction did we incorrectly flag? Lower is better.

If you sweep the threshold from 0.0 to 1.0, each setting gives one (FPR, TPR) dot. Connect all the dots and you get the **ROC curve**.

```
TPR (Recall)
1.0 |         ___-------
    |      __/
    |    _/          ← your model's curve
    |  _/
    | /
    |/_______________
   0.0              1.0  FPR (False Alarms)
```

A curve that hugs the top-left corner is a good model — it catches most positives (high TPR) while generating few false alarms (low FPR), across all thresholds.

A diagonal straight line from (0,0) to (1,1) means the model is no better than random guessing.

#### Step 3 — AUC is one number that summarises the whole curve

**AUC = the area under that curve.** Ranges from 0 to 1:
- `1.0` — perfect model (top-left corner, no false alarms ever)
- `0.5` — diagonal line, no better than a coin flip
- `≥ 0.85` — the threshold used here; generally considered reliable for a compliance use case

The key insight: AUC does **not** depend on which threshold you pick. It measures whether the model's *rankings* are good — i.e., does it consistently give genuinely risky cases a higher score than safe ones?

#### Step 4 — Why macro OVR for three classes?

Because we have **three classes** (low/medium/high), not just two, AUC is computed as **macro OVR** (One-vs-Rest):
- Compute AUC treating it as "low vs (medium+high)" — how well does the model separate low-risk cases?
- Compute AUC for "medium vs (low+high)"
- Compute AUC for "high vs (low+medium)"
- Take the unweighted average of the three

"Unweighted" (macro) means all three classes count equally, even if high-risk cases are rare. This matters for compliance — you don't want the model to ignore rare high-risk cases just because they're outnumbered.

### Hyperparameters
Settings you choose before training that control how the model learns — not learned from data. Key ones used here:

| Parameter | What it does |
|-----------|-------------|
| `max-depth=5` | How deep each decision tree can grow. Deeper = more complex, more overfitting risk. |
| `eta=0.1` | Learning rate. Smaller = more cautious updates, needs more rounds. |
| `num-round=150` | Maximum number of trees to add. |
| `early-stopping-rounds=15` | Stop adding trees if validation AUC hasn't improved for 15 rounds — prevents overfitting. |
| `subsample=0.8` | Use 80% of training rows randomly per tree. Adds variation, reduces overfitting. |
| `colsample-bytree=0.8` | Use 80% of features randomly per tree. Same idea. |
| `min-child-weight=5` | Minimum data points required in a leaf node. Higher = simpler trees. |

### Overfitting
When a model memorises the training data but fails on new cases. Symptoms: very high train AUC, low test AUC. The hyperparameters above (early stopping, subsampling, min-child-weight) all fight this.

---

## The 8 Input Features

These are the signals extracted from a completed KYC case:

| # | Feature | Type | Where it comes from |
|---|---------|------|---------------------|
| 1 | `pep_match_score` | float 0–100 | How strong the PEP/watchlist match was |
| 2 | `sanctions_hit` | 0 or 1 | Whether the person is on a sanctions list |
| 3 | `doc_authenticity_score` | float 0–100 | How authentic the identity document appears |
| 4 | `adverse_media_hits` | int | Number of negative news results found |
| 5 | `adverse_media_severity` | int 0–4 | How severe the worst adverse media result was |
| 6 | `pep_match_type` | 0/1/2 | none=0, fuzzy match=1, exact match=2 |
| 7 | `doc_status` | 0/1/2 | failed=0, unreadable=1, verified=2 |
| 8 | `country_risk_tier` | 1–5 | Risk level of the person's nationality |

**Output label**: `final_risk_label` — `low`=0, `medium`=1, `high`=2

---

## Directory Layout

```
sagemaker/
├── pipeline.py          ← Defines and optionally runs the SageMaker Pipeline
├── deploy.py            ← Deploys an approved model version to a live endpoint
└── scripts/
    ├── preprocess.py    ← Data cleaning and train/test splitting
    ├── train.py         ← XGBoost training
    └── evaluate.py      ← Metrics computation (AUC, accuracy, F1)
```

---

## Pipeline Overview

The four steps run sequentially in SageMaker managed infrastructure. You do not need to provision any servers.

```
[1] PreprocessRiskData     — clean CSV, encode strings → numbers, split 80/20
         ↓
[2] TrainRiskScorer        — XGBoost trains on the 80% split
         ↓
[3] EvaluateRiskScorer     — compute AUC on the held-out 20%
         ↓
[4] CheckModelQuality      — is AUC ≥ 0.85?
         ├─ YES → RegisterRiskScorer (queued for manual approval)
         └─ NO  → FailStep (pipeline fails — model discarded)
```

After a human approves the model in the AWS Model Registry, `deploy.py` deploys it to a live HTTPS endpoint that the KYC Lambda calls.

---

## Script Explanations

### `scripts/preprocess.py`

**What it does**: Takes the raw training CSV and prepares it for XGBoost.

The script does **not** run locally — SageMaker executes it inside a managed Docker container on a separate EC2 instance. The `/opt/ml/processing/` paths below are filesystem paths *inside that container*, not on your machine or notebook:

```
Notebook                      SageMaker (ml.m5.large EC2)
────────                      ───────────────────────────
SDK uploads                   Spins up SKLearn Docker container
preprocess.py ──── S3 ──────→ Downloads script from S3
                              Downloads your CSV from S3 → /opt/ml/processing/input/
                              Runs preprocess.py
                              Script writes → /opt/ml/processing/output/train/
                                            → /opt/ml/processing/output/test/
Notebook waits ←─── S3 ─────  Uploads output dirs to your S3 bucket
                              Container destroyed
```

Problems it solves:
- String columns like `"verified"` and `"failed"` must become numbers — XGBoost only accepts numbers. This is called **ordinal encoding** (mapping categories to ordered integers that reflect their meaning).
- Some values may be missing (`NaN`). The script fills these with safe defaults.
- Values might be out of expected range (e.g. a score of 999). The script **clips** them to valid bounds.
- The dataset is split into train and test with `stratify=y`, meaning each split has the same proportion of low/medium/high labels — important if one risk tier is rare.

**Output**: Two headerless CSVs with the label in the first column (XGBoost's convention):
```
0, 12.5, 0, 90.0, 0, 0, 0, 2, 1   ← low risk case
2, 88.0, 1, 35.0, 3, 2, 2, 0, 4   ← high risk case
```

---

### `scripts/train.py`

**What it does**: Trains the XGBoost model.

SageMaker injects the data paths as environment variables (`SM_CHANNEL_TRAIN`, etc.) so the script doesn't need to know about S3. It:
1. Loads train and validation CSVs into XGBoost's `DMatrix` format (an efficient internal matrix)
2. Configures the `multi:softprob` objective — this makes the model output a probability distribution over the 3 classes instead of a single integer
3. Trains with early stopping — it monitors validation loss every round and stops if it stops improving
4. Saves the model file (`xgboost-model`) and a metadata JSON with feature names and train AUC

**Early stopping in practice**: If round 80 is the best and nothing improves for 15 more rounds, training stops at round 95 instead of running all 150. This avoids overfitting and saves time.

---

### `scripts/evaluate.py`

**What it does**: Measures how good the trained model is on the held-out test set.

Steps:
1. Extracts the `model.tar.gz` archive SageMaker produces
2. Loads the test CSV (never seen during training)
3. Runs predictions — gets a 3-column probability matrix: `[[p_low, p_medium, p_high], ...]`
4. Computes and writes `evaluation.json`:

```json
{
  "metrics": {
    "auc_macro_ovr": { "value": 0.9123 },
    "accuracy":      { "value": 0.8750 }
  },
  "per_class": {
    "low":    { "precision": 0.91, "recall": 0.94, "f1": 0.92, "support": 120 },
    "medium": { "precision": 0.82, "recall": 0.78, "f1": 0.80, "support":  55 },
    "high":   { "precision": 0.88, "recall": 0.85, "f1": 0.86, "support":  25 }
  },
  "confusion_matrix": { "labels": ["low","medium","high"], "values": [[...]] }
}
```

The pipeline's `CheckModelQuality` step reads `metrics.auc_macro_ovr.value` from this file. If it is below 0.85 the pipeline fails.

**Confusion matrix** — a grid showing counts of what the model predicted vs what was correct. Diagonal = correct predictions.

**Precision vs Recall**:
- **Precision**: of all cases predicted "high", what fraction were truly high? (avoid false alarms)
- **Recall**: of all truly high-risk cases, what fraction did we catch? (avoid misses)
- **F1**: harmonic mean of the two — balances both concerns

---

### `pipeline.py`

**What it does**: Defines the entire 4-step pipeline as a SageMaker Pipeline object and optionally executes it.

Key concepts:
- **Pipeline parameters** — values like `AucThreshold` and `InputDataUri` that can be changed at run time without editing the code
- **PropertyFile** — SageMaker's way of wiring `evaluation.json` output from step 3 into the condition check in step 4, without downloading the file manually
- **ConditionStep** — a branch in the pipeline. If AUC ≥ threshold, go to `RegisterModel`; otherwise go to `FailStep`
- **RegisterModel** — adds the model to the SageMaker Model Registry with status `PendingManualApproval`. Nothing is deployed until a human approves it in the AWS console
- `pipeline.upsert()` — creates the pipeline if it doesn't exist, or updates it if it does (idempotent)

---

### `deploy.py`

**What it does**: Takes an approved model from the Model Registry and deploys it to a real-time HTTPS endpoint.

Steps:
1. Finds the latest `Approved` model package in the `kyc-risk-scorer` group (or accepts an explicit ARN)
2. Retrieves the correct XGBoost inference container image for the target AWS region
3. Creates a SageMaker `Model` object and calls `deploy()` — this provisions an EC2 instance (`ml.m5.large`) and starts the serving container
4. Enables **data capture** — all inputs and outputs to the endpoint are logged to S3. This is the foundation for Stage 2 monitoring/retraining.
5. Optionally runs a **smoke test**: sends a single synthetic clean-case row and confirms the endpoint returns a sensible prediction

After deployment, set the env var in your Lambda:
```
RISK_SCORER_ENDPOINT_NAME=kyc-risk-scorer
```

---

## Running the Pipeline

### Step 0 — Create the AWS infrastructure (do this once)

The SageMaker execution role and MLOps S3 bucket are **not** created manually. They are provisioned by the project's CloudFormation stacks in `templates/base/`:

| What | CloudFormation resource | Stack file |
|------|------------------------|------------|
| SageMaker execution role | `SageMakerExecutionRole` | `roles-stack.yaml` |
| MLOps S3 bucket | `KycMlOpsBucket` | `storage-stack.yaml` |

If you have already deployed those stacks (they are part of the normal project setup), the role and bucket already exist. Fetch their names from the stack outputs:

```bash
# Replace <your-stack-name> with the base stack name used when deploying
aws cloudformation describe-stacks \
  --stack-name <your-roles-stack-name> \
  --query "Stacks[0].Outputs[?OutputKey=='SageMakerExecutionRoleArn'].OutputValue" \
  --output text

aws cloudformation describe-stacks \
  --stack-name <your-storage-stack-name> \
  --query "Stacks[0].Outputs[?OutputKey=='KycMlOpsBucketName'].OutputValue" \
  --output text
```

This gives you the two values you need for every command below:
- `ROLE_ARN` — something like `arn:aws:iam::123456789012:role/myproject-sagemaker-execution-role`
- `BUCKET` — something like `myproject-mlops-123456789012-eu-west-1`

You also need:
- A training CSV uploaded to the bucket (see [Input CSV Format](#input-csv-format) below)
- Python with `sagemaker` and `boto3` installed (`pip install sagemaker boto3`)

### Step 1 — Run the training pipeline
```bash
python sagemaker/pipeline.py \
  --role   $ROLE_ARN \
  --bucket $BUCKET \
  --region eu-west-1 \
  --input-data-uri s3://$BUCKET/kyc-risk-raw/training/latest.csv \
  --auc-threshold 0.85 \
  --run
```

This takes ~20–30 minutes on first run. You can monitor progress in the SageMaker console under **Pipelines**.

### Step 2 — Approve the model (manual)
After the pipeline succeeds, go to **SageMaker → Model Registry → kyc-risk-scorer** in the AWS console. Review the evaluation metrics attached to the model version (AUC, per-class F1) and click **Approve**. Nothing is deployed until you do this.

### Step 3 — Deploy the endpoint
```bash
python sagemaker/deploy.py \
  --role   $ROLE_ARN \
  --bucket $BUCKET \
  --region eu-west-1 \
  --smoke-test
```

### Step 4 — Wire up the Lambda
Set `RISK_SCORER_ENDPOINT_NAME=kyc-risk-scorer` in the Lambda environment. The `score_case_risk` tool in `crew/tools/risk_scoring_tool.py` will then call the endpoint automatically.

---

## Input CSV Format

```
customer_id, pep_match_score, pep_match_type, sanctions_hit, doc_status,
doc_authenticity_score, adverse_media_hits, adverse_media_severity,
country_risk_tier, final_risk_label
```

- `final_risk_label` can be the string `low`/`medium`/`high`/`rejected`, or the integer `0`/`1`/`2`
- `pep_match_type` can be the string `none`/`fuzzy`/`exact`, or the integer `0`/`1`/`2`
- `doc_status` can be the string `failed`/`unreadable`/`verified`, or the integer `0`/`1`/`2`
- Optional columns `event_time`, `confirmed_by`, `confirmed_at` are dropped automatically

---

## S3 Artifacts Written by the Pipeline

```
s3://{bucket}/
  kyc-risk-raw/training/latest.csv        ← your input
  kyc-risk-processed/train/train.csv      ← preprocess output (train split)
  kyc-risk-processed/test/test.csv        ← preprocess output (test split)
  kyc-risk-model/                         ← trained model artifact (model.tar.gz)
  kyc-risk-evaluation/evaluation.json     ← AUC + per-class metrics
  kyc-risk-capture/{endpoint}/            ← live inference data capture (post-deploy)
```
