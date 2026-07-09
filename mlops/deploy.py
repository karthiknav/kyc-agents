"""
Deploy an approved KYC risk scorer model to a SageMaker endpoint.

Run this script after manually approving a model version in the
SageMaker Model Registry console (or via API).

Usage
-----
python sagemaker/deploy.py \
    --role  arn:aws:iam::123456789012:role/SageMakerExecutionRole \
    --bucket kyc-mlops \
    [--region eu-west-1] \
    [--endpoint-name kyc-risk-scorer] \
    [--instance-type ml.m5.large] \
    [--model-package-arn arn:aws:sagemaker:...:model-package/kyc-risk-scorer/1]

If --model-package-arn is omitted, the script finds the latest
Approved version in the 'kyc-risk-scorer' model package group.

Environment variable written by this script
-------------------------------------------
After deployment, set in your Lambda / .env:
  RISK_SCORER_ENDPOINT_NAME=kyc-risk-scorer
"""

import argparse
import json
import logging
import time

import boto3
from sagemaker.core import image_uris

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_PACKAGE_GROUP = "kyc-risk-scorer"
DEFAULT_ENDPOINT_NAME = "kyc-risk-scorer"


def _latest_approved_arn(sm_client, group_name: str) -> str:
    """Return the ARN of the most recently approved model package in the group."""
    response = sm_client.list_model_packages(
        ModelPackageGroupName=group_name,
        ModelApprovalStatus="Approved",
        SortBy="CreationTime",
        SortOrder="Descending",
        MaxResults=1,
    )
    packages = response.get("ModelPackageSummaryList", [])
    if not packages:
        raise RuntimeError(
            f"No Approved model packages found in group '{group_name}'. "
            "Approve a version in the SageMaker Model Registry first."
        )
    arn = packages[0]["ModelPackageArn"]
    logger.info("Latest approved model package: %s", arn)
    return arn


def deploy(
    *,
    role: str,
    bucket: str,
    region: str = "us-east-1",
    endpoint_name: str = DEFAULT_ENDPOINT_NAME,
    instance_type: str = "ml.m5.large",
    model_package_arn: str | None = None,
) -> str:
    sm_client = boto3.client("sagemaker", region_name=region)

    arn = model_package_arn or _latest_approved_arn(sm_client, MODEL_PACKAGE_GROUP)

    xgb_image = image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.7-1",
        instance_type=instance_type,
        image_scope="inference",
    )

    model_name = f"kyc-risk-scorer-{int(time.time())}"
    sm_client.create_model(
        ModelName=model_name,
        PrimaryContainer={
            "Image": xgb_image,
            "ModelDataUrl": _model_data_from_package(sm_client, arn),
        },
        ExecutionRoleArn=role,
    )

    config_name = f"{endpoint_name}-config-{int(time.time())}"
    sm_client.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[{
            "VariantName": "AllTraffic",
            "ModelName": model_name,
            "InitialInstanceCount": 1,
            "InstanceType": instance_type,
            "InitialVariantWeight": 1.0,
        }],
        DataCaptureConfig={
            "EnableCapture": True,
            "InitialSamplingPercentage": 100,
            "DestinationS3Uri": f"s3://{bucket}/kyc-risk-capture/{endpoint_name}",
            "CaptureOptions": [
                {"CaptureMode": "Input"},
                {"CaptureMode": "Output"},
            ],
        },
    )

    logger.info("Deploying to endpoint '%s' on %s …", endpoint_name, instance_type)
    try:
        sm_client.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)
    except sm_client.exceptions.from_code("ValidationException"):
        sm_client.update_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)

    sm_client.get_waiter("endpoint_in_service").wait(EndpointName=endpoint_name)

    logger.info("Endpoint '%s' is InService.", endpoint_name)
    logger.info("Set  RISK_SCORER_ENDPOINT_NAME=%s  in your Lambda environment.", endpoint_name)
    return endpoint_name


def _model_data_from_package(sm_client, arn: str) -> str:
    desc = sm_client.describe_model_package(ModelPackageName=arn)
    containers = desc["InferenceSpecification"]["Containers"]
    return containers[0]["ModelDataUrl"]


def smoke_test(endpoint_name: str, region: str) -> None:
    """Send a synthetic low-risk case to verify the endpoint is healthy."""
    rt = boto3.client("sagemaker-runtime", region_name=region)
    # feature order: pep_match_score, sanctions_hit, doc_authenticity_score,
    #                adverse_media_hits, adverse_media_severity,
    #                pep_match_type, doc_status, country_risk_tier
    payload = "0,0,95,0,0,0,2,1"   # clean case: no PEP/sanctions, verified doc, no media
    response = rt.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="text/csv",
        Body=payload,
    )
    raw = response["Body"].read().decode()
    proba = [float(x) for x in raw.strip().split(",")]
    predicted = ["low", "medium", "high"][proba.index(max(proba))]
    logger.info("Smoke test → probabilities %s → predicted '%s'", proba, predicted)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy approved KYC risk scorer to SageMaker endpoint")
    parser.add_argument("--role", required=True, help="SageMaker execution role ARN")
    parser.add_argument("--bucket", required=True, help="S3 bucket (for data capture output)")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--endpoint-name", default=DEFAULT_ENDPOINT_NAME)
    parser.add_argument("--instance-type", default="ml.m5.large")
    parser.add_argument("--model-package-arn", default=None, help="Specific model package ARN to deploy")
    parser.add_argument("--smoke-test", action="store_true", help="Run a synthetic prediction after deploy")
    args = parser.parse_args()

    ep = deploy(
        role=args.role,
        bucket=args.bucket,
        region=args.region,
        endpoint_name=args.endpoint_name,
        instance_type=args.instance_type,
        model_package_arn=args.model_package_arn,
    )

    if args.smoke_test:
        smoke_test(ep, args.region)
