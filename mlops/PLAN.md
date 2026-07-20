# Plan: SageMaker MLOps — CD Pipeline + Monitoring + Auto-Retraining

## Status

| Piece | Status |
|---|---|
| Stack 1 — CD pipeline (approval → deploy) | **Built** — `templates/mlops-cd-pipeline-stack.yaml` |
| Baseline job (feeds the monitor) | **Built** — `GenerateDataQualityBaseline` step in `pipeline.py`, runs alongside `RegisterRiskScorer` |
| Stack 2 — Data Quality monitoring + drift alarm | **Built, alert-only** — `templates/mlops-monitoring-stack.yaml` |
| Auto-retrain on drift (EventBridge → StartPipelineExecution) | **Deliberately not built.** See "Why not auto-retrain on drift?" below. |
| Labeling/feedback loop (confirmed case outcomes → training CSV) | **Not built** — prerequisite for auto-retrain ever being meaningful |

## The Full Loop (as actually implemented)

```
[MONITOR]
Deployed endpoint → data captured to S3 (deploy.py, DataCaptureConfig)
SageMaker Data Quality Monitor (daily schedule, mlops-monitoring-stack.yaml)
  compares live input features to training baseline stats
  violations → S3 report + CloudWatch metric
        ↓
CloudWatch Alarm (drift % > threshold)
        ↓
[ALERT — not auto-retrain]
SNS topic → ML/compliance team investigates
  - pipeline/schema bug (e.g. upstream API changed)? → fix the code
  - genuine population shift? → needs fresh labeled data before retraining helps
  - in the meantime: risk_scoring_tool.py's existing heuristic_fallback path
    can be forced on to stop trusting a drifted model
        ↓
[TRAINING PIPELINE] (pipeline.py) — run manually, or automatically once a
labeling loop exists to refresh InputDataUri with confirmed outcomes
Preprocess → Train → Evaluate → CheckAUC ≥ 0.85
        ↓
RegisterModel (PendingManualApproval) + GenerateDataQualityBaseline
        ↓
[HUMAN GATE]
Compliance officer reviews AUC + per-class F1 in Model Registry
Clicks Approve
        ↓
[CD PIPELINE] (Stack 1 — built)
EventBridge (model approved) → CodePipeline → deploy.py → endpoint updated
        ↓
Loop back to monitoring ↑
```

### Why not auto-retrain on drift?

`pipeline.py`'s `InputDataUri` parameter defaults to a fixed `latest.csv`. Wiring
the drift alarm straight to `StartPipelineExecution` would retrain against that
same static file every time — same distribution in, same model out, drift
unaddressed. Auto-retrain only becomes useful once something refreshes the
training CSV with recently-confirmed case outcomes before each run (e.g. a
Lambda that queries DynamoDB for confirmed decisions and appends them). Until
that exists, the alarm is wired to SNS only. See `mlops/README.md` → "Drift
Monitoring — Design Notes" for the full reasoning.

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

### Stack 2 — `templates/mlops-monitoring-stack.yaml` (built)
Handles data drift detection and alerting. **Deliberately alert-only — no auto-retrain trigger** (see "Why not auto-retrain on drift?" above).

**Parameters**: `SageMakerExecutionRoleArn`, `KycMlOpsBucketName`, `EndpointName` (default: kyc-risk-scorer), `MonitorImageUri` (region-specific model-monitor analyzer image — retrieve via the SageMaker SDK, see template description), `BaselineS3Uri` (output of the `GenerateDataQualityBaseline` pipeline step), `MonitoringScheduleExpression` (default: `cron(0 6 * * ? *)` — daily 6am UTC), `DriftThresholdPercentage` (default: 20), `MetricNamespace`/`MetricName` (verify exact values in CloudWatch after the first schedule run), `NotificationEmail` (optional)

**Resources** (6):

| Resource | Type | Purpose |
|----------|------|---------|
| `DataQualityJobDefinition` | `AWS::SageMaker::DataQualityJobDefinition` | Defines what to compare (live vs baseline) and where to write violations |
| `MonitoringSchedule` | `AWS::SageMaker::MonitoringSchedule` | Runs the job on schedule, references `DataQualityJobDefinition` |
| `DriftAlertTopic` | `AWS::SNS::Topic` | Where drift alerts go — subscribe the ML/compliance team |
| `DriftAlertTopicPolicy` | `AWS::SNS::TopicPolicy` | Allows CloudWatch alarms to publish to the topic |
| `DriftAlertSubscription` | `AWS::SNS::Subscription` | Optional email subscription (only if `NotificationEmail` is set) |
| `DriftViolationAlarm` | CloudWatch Alarm | Triggers when the drift metric exceeds `DriftThresholdPercentage`; action = publish to `DriftAlertTopic` (not `StartPipelineExecution`) |

`DataQualityJobDefinition` config:
- `EndpointName`: the live endpoint (`kyc-risk-scorer`)
- `DataQualityBaselineConfig`: `{BaselineS3Uri}constraints.json` / `{BaselineS3Uri}statistics.json`
- Output violations S3: `s3://{KycMlOpsBucket}/kyc-risk-monitoring/violations/`
- Role: `SageMakerExecutionRoleArn` (already has required permissions)

CloudWatch alarm metric: `aws/sagemaker/Endpoints/data-metrics` (namespace/metric name are parameters — the exact per-feature metric name SageMaker publishes should be confirmed in the CloudWatch console after the first `MonitoringSchedule` execution, then set via stack update if it differs from the default).

**If/when the labeling loop is built**, extending this stack to auto-retrain means adding an `EventBridgeSageMakerPipelineRole` (IAM) + an EventBridge rule watching `DriftViolationAlarm` state → `ALARM`, targeting `sagemaker:StartPipelineExecution` — but only once something also refreshes `InputDataUri` with fresh confirmed-label data first.

---

## One-Time Baseline Job (prerequisite for Stack 2) — built

`mlops/pipeline.py` now has a `GenerateDataQualityBaseline` step (`QualityCheckStep`, using `DataQualityCheckConfig`) that runs alongside `RegisterRiskScorer` — i.e. only when a model passes the AUC gate and gets registered, so the baseline always matches the training data behind the most recently approved model. It reads the same `train` split `TrainRiskScorer` uses and writes to `BaselineOutputUri` (pipeline parameter, defaults to `s3://{bucket}/kyc-risk-monitoring/baseline/`).

That S3 URI is the `BaselineS3Uri` parameter for Stack 2.

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `templates/mlops-cd-pipeline-stack.yaml` | **Done** — Stack 1 (6 resources) |
| `templates/mlops-monitoring-stack.yaml` | **Done** — Stack 2, alert-only (6 resources) |
| `mlops/pipeline.py` | **Done** — added `GenerateDataQualityBaseline` step |
| `templates/roles-stack.yaml` | No change — SageMakerExecutionRole already sufficient |
| `mlops/deploy.py` | No change — works as-is |
| Labeling/feedback loop (DynamoDB confirmed outcomes → training CSV) | **Not started** — needed before auto-retrain is worth building |

---

## Deployment Order

```bash
# 1. Deploy CD pipeline stack
aws cloudformation deploy \
  --template-file templates/mlops-cd-pipeline-stack.yaml \
  --stack-name kyc-mlops-cd-pipeline \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides RolesStackName=<...> StorageStackName=<...> \
    SageMakerExecutionRoleArn=<...> KycMlOpsBucketName=<...> \
    GitHubConnectionArn=<...> GitHubRepo=<...>

# 2. Run training pipeline once (registers a model + generates the baseline)
python mlops/pipeline.py --role $ROLE_ARN --bucket $BUCKET --run

# 3. Approve model in Model Registry → CD pipeline auto-deploys endpoint

# 4. Retrieve the region's model-monitor analyzer image URI
python -c "from sagemaker import image_uris; print(image_uris.retrieve(framework='model-monitor', region='$REGION'))"

# 5. Deploy monitoring stack (endpoint must exist first)
aws cloudformation deploy \
  --template-file templates/mlops-monitoring-stack.yaml \
  --stack-name kyc-mlops-monitoring \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    SageMakerExecutionRoleArn=$ROLE_ARN \
    KycMlOpsBucketName=$BUCKET \
    MonitorImageUri=<from step 4> \
    BaselineS3Uri=s3://$BUCKET/kyc-risk-monitoring/baseline/ \
    NotificationEmail=<optional>
```

---

## Verification

1. **CD pipeline**: Approve a model → verify CodePipeline execution starts → endpoint `InService`
2. **Monitor**: Check SageMaker console → Endpoints → kyc-risk-scorer → Data Quality tab — schedule shows next run time
3. **Drift alarm**: Manually publish a test CloudWatch metric exceeding threshold → verify `DriftAlertTopic` receives a notification (not a pipeline execution)
4. **End-to-end**: Send intentionally skewed feature data to the endpoint → wait for daily monitor run → verify alarm fires → verify SNS notification arrives
5. **Auto-retrain (future)**: not applicable until the labeling loop and the EventBridge extension described above are built
