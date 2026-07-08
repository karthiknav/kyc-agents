# Plan: SageMaker MLOps — CD Pipeline + Monitoring + Auto-Retraining

## The Full Loop

```
[MONITOR]
Deployed endpoint → data captured to S3 (already wired in deploy.py)
SageMaker Data Quality Monitor (daily schedule)
  compares live input features to training baseline stats
  violations → S3 report + CloudWatch metric
        ↓
CloudWatch Alarm (violation rate > threshold)
        ↓
[RETRAIN TRIGGER]
EventBridge rule (Alarm state → ALARM)
        ↓
StartPipelineExecution on existing SageMaker training pipeline
        ↓
[TRAINING PIPELINE] (pipeline.py — unchanged)
Preprocess → Train → Evaluate → CheckAUC ≥ 0.85
        ↓
RegisterModel (PendingManualApproval) + notify team
        ↓
[HUMAN GATE]
Compliance officer reviews AUC + per-class F1 in Model Registry
Clicks Approve
        ↓
[CD PIPELINE]
EventBridge (model approved) → CodePipeline → deploy.py → endpoint updated
        ↓
Loop back to monitoring ↑
```

---

## Two New CloudFormation Stacks

### Stack 1 — `templates/mlops-cd-pipeline-stack.yaml`
Handles the approval → deploy leg.

**Parameters**: `RoleStackName`, `StorageStackName`, `GitHubConnectionArn`, `GitHubOwner`, `GitHubRepo`, `GitHubBranch` (default: main)

**Resources** (6):

| Resource | Type | Purpose |
|----------|------|---------|
| `MlopsDeployArtifactBucket` | S3 | Pipeline artifacts (30-day lifecycle) |
| `MlopsDeployCodeBuildRole` | IAM Role | CodeBuild permissions for deploy.py |
| `MlopsDeployBuildProject` | CodeBuild | Runs `python mlops/deploy.py --smoke-test` |
| `EventBridgeCodePipelineRole` | IAM Role | Allows EventBridge to start the pipeline |
| `ModelApprovalEventRule` | EventBridge Rule | Fires on `ModelApprovalStatus=Approved` in `kyc-risk-scorer` group |
| `MlopsDeployPipeline` | CodePipeline V2 | Source (GitHub) → Build (deploy.py) |

`MlopsDeployCodeBuildRole` needs:
- SageMaker: `CreateModel`, `CreateEndpointConfig`, `CreateEndpoint`, `UpdateEndpoint`, `DescribeEndpoint`, `ListModelPackages`, `DescribeModelPackage`
- `iam:PassRole` scoped to imported `SageMakerExecutionRoleArn`
- `s3:GetObject/PutObject/ListBucket` on `KycMlOpsBucket` + artifact bucket
- `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`
- CloudWatch Logs

EventBridge rule pattern:
```json
{
  "source": ["aws.sagemaker"],
  "detail-type": ["SageMaker Model Package State Change"],
  "detail": {
    "ModelPackageGroupName": ["kyc-risk-scorer"],
    "ModelApprovalStatus": ["Approved"]
  }
}
```

---

### Stack 2 — `templates/mlops-monitoring-stack.yaml`
Handles data drift detection and automatic retraining trigger.

**Parameters**: `RoleStackName`, `StorageStackName`, `EndpointName` (default: kyc-risk-scorer), `TrainingPipelineName` (default: kyc-risk-scorer), `BaselineS3Uri` (output of one-time baseline job), `MonitoringScheduleExpression` (default: `cron(0 6 * * ? *)` — daily 6am UTC)

**Resources** (5):

| Resource | Type | Purpose |
|----------|------|---------|
| `DataQualityJobDefinition` | `AWS::SageMaker::DataQualityJobDefinition` | Defines what to compare (live vs baseline) and where to write violations |
| `MonitoringSchedule` | `AWS::SageMaker::MonitoringSchedule` | Runs the job on schedule, references `DataQualityJobDefinition` |
| `DriftViolationAlarm` | CloudWatch Alarm | Triggers when `feature_baseline_drift_percentage > 20` for 1 evaluation period |
| `EventBridgeSageMakerPipelineRole` | IAM Role | Allows EventBridge to call `sagemaker:StartPipelineExecution` |
| `DriftRetrainingRule` | EventBridge Rule | Watches alarm state change → ALARM; starts training pipeline |

`DataQualityJobDefinition` config:
- `EndpointName`: the live endpoint (`kyc-risk-scorer`)
- `BaselineConstraintsS3Uri` / `BaselineStatisticsS3Uri`: from the baseline job (see below)
- Output violations S3: `s3://{KycMlOpsBucket}/kyc-risk-monitoring/violations/`
- Role: imported `SageMakerExecutionRoleArn` (already has required permissions)

CloudWatch alarm metric: `aws/sagemaker/Endpoints/data-metrics`, dimension `EndpointName=kyc-risk-scorer`

EventBridge retraining rule pattern:
```json
{
  "source": ["aws.cloudwatch"],
  "detail-type": ["CloudWatch Alarm State Change"],
  "detail": {
    "alarmName": ["kyc-risk-drift-alarm"],
    "state": { "value": ["ALARM"] }
  }
}
```
Target: `sagemaker:StartPipelineExecution` on the training pipeline ARN.

---

## One-Time Baseline Job (prerequisite for Stack 2)

Before deploying the monitoring stack, run a baseline computation job once against the training data. This generates the statistics and constraints files the monitor compares against.

Add a step to `mlops/pipeline.py` (optional final step) **or** run it as a standalone script after first training:

```python
from sagemaker.model_monitor import DefaultModelMonitor
monitor = DefaultModelMonitor(role=role, ...)
monitor.suggest_baseline(
    baseline_dataset=f"s3://{bucket}/kyc-risk-processed/train/train.csv",
    dataset_format=DatasetFormat.csv(header=False),
    output_s3_uri=f"s3://{bucket}/kyc-risk-monitoring/baseline/",
)
```

Output S3 URI (`s3://{bucket}/kyc-risk-monitoring/baseline/`) is the `BaselineS3Uri` parameter for Stack 2.

**Recommended**: add this as a final step in `pipeline.py` so the baseline always matches the model that was just trained (baseline drift against stale training data is a common pitfall).

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `templates/mlops-cd-pipeline-stack.yaml` | **Create** — Stack 1 (6 resources) |
| `templates/mlops-monitoring-stack.yaml` | **Create** — Stack 2 (5 resources) |
| `mlops/pipeline.py` | **Modify** — add optional baseline job step at end of pipeline |
| `templates/roles-stack.yaml` | **No change** — SageMakerExecutionRole already sufficient |
| `mlops/deploy.py` | **No change** — works as-is |

---

## Deployment Order

```bash
# 1. Deploy CD pipeline stack
aws cloudformation deploy \
  --template-file templates/mlops-cd-pipeline-stack.yaml \
  --stack-name kyc-mlops-cd-pipeline \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides RoleStackName=<...> StorageStackName=<...> \
    GitHubConnectionArn=<...> GitHubOwner=<...> GitHubRepo=<...>

# 2. Run training pipeline once (to have a model + generate baseline)
python mlops/pipeline.py --role $ROLE_ARN --bucket $BUCKET --run

# 3. Approve model in Model Registry → CD pipeline auto-deploys endpoint

# 4. Deploy monitoring stack (endpoint must exist first)
aws cloudformation deploy \
  --template-file templates/mlops-monitoring-stack.yaml \
  --stack-name kyc-mlops-monitoring \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides RoleStackName=<...> StorageStackName=<...> \
    BaselineS3Uri=s3://$BUCKET/kyc-risk-monitoring/baseline/
```

---

## Verification

1. **CD pipeline**: Approve a model → verify CodePipeline execution starts → endpoint `InService`
2. **Monitor**: Check SageMaker console → Endpoints → kyc-risk-scorer → Data Quality tab — schedule shows next run time
3. **Drift alarm**: Manually publish a test CloudWatch metric exceeding threshold → verify EventBridge fires → verify SageMaker Pipeline execution starts
4. **End-to-end**: Send intentionally skewed feature data to the endpoint → wait for daily monitor run → verify alarm → verify retraining pipeline kicks off
