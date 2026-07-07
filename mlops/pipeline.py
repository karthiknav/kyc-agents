"""
KYC Risk Scorer — SageMaker Pipeline
======================================
Steps
-----
1. PreprocessRiskData  - SKLearnProcessor: encode features, split 80/20
2. TrainRiskScorer     - XGBoost custom script (multi:softprob, 3 classes)
3. EvaluateRiskScorer  - SKLearnProcessor: AUC + per-class metrics
4. CheckModelQuality   - ConditionStep: AUC >= threshold?
   ├─ pass → RegisterRiskScorer  (PendingManualApproval)
   └─ fail → ModelQualityCheckFailed (FailStep)

Usage
-----
python sagemaker/pipeline.py \
    --role  arn:aws:iam::123456789012:role/SageMakerExecutionRole \
    --bucket kyc-mlops \
    [--region eu-west-1] \
    [--input-data-uri s3://kyc-mlops/kyc-risk-raw/training/latest.csv] \
    [--auc-threshold 0.85] \
    [--run]

The pipeline can also be created once and re-executed from the console or
via `pipeline.start(parameters={...})`.
"""

import argparse
import os

import boto3
import sagemaker
from sagemaker.inputs import TrainingInput
from sagemaker.model_metrics import MetricsSource, ModelMetrics
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.sklearn.processing import SKLearnProcessor
from sagemaker.workflow.conditions import ConditionGreaterThanOrEqualTo
from sagemaker.workflow.condition_step import ConditionStep
from sagemaker.workflow.fail_step import FailStep
from sagemaker.workflow.functions import JsonGet
from sagemaker.workflow.parameters import ParameterFloat, ParameterString
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.step_collections import RegisterModel
from sagemaker.workflow.steps import ProcessingStep, TrainingStep
from sagemaker.xgboost.estimator import XGBoost

PIPELINE_NAME = "kyc-risk-scorer"
MODEL_PACKAGE_GROUP = "kyc-risk-scorer"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_pipeline(
    *,
    role: str,
    bucket: str,
    region: str = "us-east-1",
    pipeline_name: str = PIPELINE_NAME,
) -> Pipeline:
    session = sagemaker.Session(boto_session=boto3.Session(region_name=region))

    # ── Pipeline Parameters ──────────────────────────────────────────────────
    # These can be overridden at execution time without changing the pipeline definition.
    p_input_uri = ParameterString(
        name="InputDataUri",
        default_value=f"s3://{bucket}/kyc-risk-raw/training/latest.csv",
    )
    p_auc_threshold = ParameterFloat(name="AucThreshold", default_value=0.85)
    p_approval_status = ParameterString(
        name="ModelApprovalStatus",
        default_value="PendingManualApproval",
    )

    # ── Step 1 · Preprocess ──────────────────────────────────────────────────
    sklearn_proc = SKLearnProcessor(
        framework_version="1.2-1",
        instance_type="ml.m5.large",
        instance_count=1,
        role=role,
        sagemaker_session=session,
    )
    step_preprocess = ProcessingStep(
        name="PreprocessRiskData",
        processor=sklearn_proc,
        inputs=[
            ProcessingInput(
                source=p_input_uri,
                destination="/opt/ml/processing/input",
                s3_data_distribution_type="FullyReplicated",
            )
        ],
        outputs=[
            ProcessingOutput(         # index 0 — train split
                output_name="train",
                source="/opt/ml/processing/output/train",
                destination=f"s3://{bucket}/kyc-risk-processed/train",
            ),
            ProcessingOutput(         # index 1 — test split
                output_name="test",
                source="/opt/ml/processing/output/test",
                destination=f"s3://{bucket}/kyc-risk-processed/test",
            ),
        ],
        code=os.path.join(BASE_DIR, "scripts", "preprocess.py"),
        job_arguments=["--test-size", "0.2", "--random-seed", "42"],
    )

    # ── Step 2 · Train ───────────────────────────────────────────────────────
    xgb_estimator = XGBoost(
        entry_point="train.py",
        source_dir=os.path.join(BASE_DIR, "scripts"),
        framework_version="1.7-1",
        instance_type="ml.m5.xlarge",
        instance_count=1,
        role=role,
        sagemaker_session=session,
        output_path=f"s3://{bucket}/kyc-risk-model",
        hyperparameters={
            "max-depth": 5,
            "eta": 0.1,
            "num-round": 150,
            "subsample": 0.8,
            "colsample-bytree": 0.8,
            "min-child-weight": 5,
            "early-stopping-rounds": 15,
        },
    )
    step_train = TrainingStep(
        name="TrainRiskScorer",
        estimator=xgb_estimator,
        inputs={
            "train": TrainingInput(
                # Resolved at runtime from the preprocess step output (index 0)
                s3_data=step_preprocess.properties.ProcessingOutputConfig.Outputs[0].S3Output.S3Uri,
                content_type="text/csv",
            ),
            "validation": TrainingInput(
                # Test split used as validation for early stopping (index 1)
                s3_data=step_preprocess.properties.ProcessingOutputConfig.Outputs[1].S3Output.S3Uri,
                content_type="text/csv",
            ),
        },
    )

    # ── Step 3 · Evaluate ────────────────────────────────────────────────────
    # The PropertyFile lets ConditionStep read AUC out of evaluation.json
    # without downloading the file at pipeline-definition time.
    eval_output_s3 = f"s3://{bucket}/kyc-risk-evaluation"
    evaluation_report = PropertyFile(
        name="EvaluationReport",
        output_name="evaluation",
        path="evaluation.json",
    )
    eval_proc = SKLearnProcessor(
        framework_version="1.2-1",
        instance_type="ml.m5.large",
        instance_count=1,
        role=role,
        sagemaker_session=session,
    )
    step_evaluate = ProcessingStep(
        name="EvaluateRiskScorer",
        processor=eval_proc,
        inputs=[
            ProcessingInput(
                source=step_train.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/input/model",
            ),
            ProcessingInput(
                source=step_preprocess.properties.ProcessingOutputConfig.Outputs[1].S3Output.S3Uri,
                destination="/opt/ml/processing/input/test",
            ),
        ],
        outputs=[
            ProcessingOutput(
                output_name="evaluation",
                source="/opt/ml/processing/evaluation",
                destination=eval_output_s3,
            )
        ],
        code=os.path.join(BASE_DIR, "scripts", "evaluate.py"),
        property_files=[evaluation_report],
    )

    # ── Step 4 · Conditional register ────────────────────────────────────────
    model_metrics = ModelMetrics(
        model_statistics=MetricsSource(
            s3_uri=f"{eval_output_s3}/evaluation.json",
            content_type="application/json",
        )
    )
    step_register = RegisterModel(
        name="RegisterRiskScorer",
        estimator=xgb_estimator,
        model_data=step_train.properties.ModelArtifacts.S3ModelArtifacts,
        content_types=["text/csv", "application/json"],
        response_types=["application/json"],
        inference_instances=["ml.m5.large", "ml.m5.xlarge"],
        transform_instances=["ml.m5.large"],
        model_package_group_name=MODEL_PACKAGE_GROUP,
        approval_status=p_approval_status,
        model_metrics=model_metrics,
    )
    step_fail = FailStep(
        name="ModelQualityCheckFailed",
        error_message="AUC below threshold — model not registered. Review evaluation report.",
    )
    step_condition = ConditionStep(
        name="CheckModelQuality",
        conditions=[
            ConditionGreaterThanOrEqualTo(
                left=JsonGet(
                    step_name=step_evaluate.name,
                    property_file=evaluation_report,
                    json_path="metrics.auc_macro_ovr.value",
                ),
                right=p_auc_threshold,
            )
        ],
        if_steps=[step_register],
        else_steps=[step_fail],
    )

    return Pipeline(
        name=pipeline_name,
        parameters=[p_input_uri, p_auc_threshold, p_approval_status],
        steps=[step_preprocess, step_train, step_evaluate, step_condition],
        sagemaker_session=session,
    )


def _ensure_model_package_group(client, group_name: str) -> None:
    try:
        client.describe_model_package_group(ModelPackageGroupName=group_name)
    except client.exceptions.ClientError:
        client.create_model_package_group(
            ModelPackageGroupName=group_name,
            ModelPackageGroupDescription="KYC risk scorer — XGBoost, 3-class risk tier",
        )
        print(f"Created model package group '{group_name}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create (and optionally run) the KYC risk scorer pipeline")
    parser.add_argument("--role", required=True, help="SageMaker execution role ARN")
    parser.add_argument("--bucket", required=True, help="S3 bucket for artifacts and processed data")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--input-data-uri", help="Override default S3 URI for training CSV")
    parser.add_argument("--auc-threshold", type=float, default=0.85)
    parser.add_argument("--run", action="store_true", help="Execute the pipeline after upsert")
    args = parser.parse_args()

    sm_client = boto3.client("sagemaker", region_name=args.region)
    _ensure_model_package_group(sm_client, MODEL_PACKAGE_GROUP)

    pipeline = create_pipeline(role=args.role, bucket=args.bucket, region=args.region)
    pipeline.upsert(role_arn=args.role)
    print(f"Pipeline '{PIPELINE_NAME}' upserted successfully.")

    if args.run:
        run_params: dict = {"AucThreshold": args.auc_threshold}
        if args.input_data_uri:
            run_params["InputDataUri"] = args.input_data_uri

        execution = pipeline.start(parameters=run_params)
        print(f"Execution started: {execution.arn}")
        print("Waiting for completion (this takes ~20-30 min on first run)…")
        execution.wait()

        print("\nStep results:")
        for step in execution.list_steps():
            status = step["StepStatus"]
            name = step["StepName"]
            print(f"  {'✓' if status == 'Succeeded' else '✗'}  {name:<45}  {status}")
