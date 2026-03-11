# Deploying mock-service to AWS Elastic Beanstalk

This guide uses the included EB config and packaging scripts for a simple, non-complicated setup. SQLite is used with a writable `data/` directory (no persistent EBS/EFS).

**Deploy order:** Deploy mock-service (Beanstalk) **before** the main agent stack. The agent uses the mock-service URL as `BRP_API_URL` to call the BRP document-lookup API. After the Beanstalk stack is created, get the `EnvironmentURL` output and set `BRP_API_URL` when configuring the agent runtime. Then run the full-stack deploy (`./scripts/deploy.sh`).

---

## Prerequisites

- Node.js 20+ and npm
- AWS CLI and EB CLI installed and configured (`aws configure`, `eb init`)

---

## 1. Package the application

From the **mock-service** directory:

```bash
npm install
npm run package:eb
```

This will:

- Run `npm run build` (compile TypeScript to `dist/`)
- Create **deploy.zip** containing: `dist/`, `mocks/`, `package.json`, `package-lock.json`, `Procfile`, `.ebextensions/`

Optional: custom output path

```bash
node scripts/package-for-eb.js my-release.zip
```

On Windows you can use:

```powershell
.\scripts\package-for-eb.ps1
# or with custom name:
.\scripts\package-for-eb.ps1 -OutZip my-release.zip
```

On Linux/macOS:

```bash
bash scripts/package-for-eb.sh
# or: bash scripts/package-for-eb.sh my-release.zip
```

---

## 2. Create the Elastic Beanstalk environment (first time)

```bash
eb init
# Choose region, create/new application name, platform: Node.js 20 (or latest Node.js)
# Do not set up SSH unless you need it.

eb create mock-service-env
# Or: eb create mock-service-env --single  (single instance, simpler for a mock)
```

---

## 3. Deploy

**Option A — Deploy the zip you built**

```bash
eb deploy
```

If you use `eb deploy` without packaging first, ensure you have run `npm run build` so `dist/` exists. The project’s `.ebignore` excludes source and dev files so that `dist/`, `mocks/`, and config are included.

**Option B — Deploy a pre-built zip**

```bash
npm run package:eb
eb deploy
```

Or upload **deploy.zip** in the AWS Console: Elastic Beanstalk → your application → Environment → Upload and deploy.

---

## 3b. Deploy via CloudFormation (no EB CLI)

You can provision the Elastic Beanstalk application and environment using **AWS CloudFormation** instead of the EB CLI. Templates live in the repo root **`templates/mock-service/`** and deployment is orchestrated by **`scripts/deploy.sh`** (run from the mock-service directory).

### Templates

| File | Purpose |
|------|---------|
| `templates/mock-service/elastic-beanstalk.yaml` | EB Application, ApplicationVersion (from S3), and Environment (Node.js, SingleInstance) |
| `templates/mock-service/s3-artifacts-bucket.yaml` | Optional: S3 bucket for storing `deploy.zip` |
| `templates/mock-service/parameters.example.json` | Example parameters file |

### Deploy with deploy_mock_service.sh (recommended)

From the **repo root** (kyc-agents), run:

```bash
# Package only (creates mock-service/deploy.zip)
./scripts/deploy_mock_service.sh

# Package + upload to S3
S3_BUCKET=your-bucket-name ./scripts/deploy_mock_service.sh

# Package + upload + create or update CloudFormation stack
S3_BUCKET=your-bucket-name STACK_NAME=kyc-mock-service-eb ./scripts/deploy_mock_service.sh
```

Packaging only (from repo root): `./scripts/package_mock_service_for_eb.sh`

**Environment variables for deploy_mock_service.sh:**

| Variable | Description |
|---------|-------------|
| `S3_BUCKET` | Upload `deploy.zip` to this bucket; required for stack create/update |
| `S3_KEY` | S3 key for the zip (default: `mock-service/deploy.zip`) |
| `STACK_NAME` | CloudFormation stack name (default: `kyc-mock-service-eb`) |
| `DEPLOY_SKIP_PACKAGE` | Set to `1` to skip packaging and use existing `mock-service/deploy.zip` |

After the stack is `CREATE_COMPLETE` or `UPDATE_COMPLETE`, get the application URL and set it as **`BRP_API_URL`** for the agent (e.g. agent runtime environment):

```bash
aws cloudformation describe-stacks --stack-name kyc-mock-service-eb \
  --query "Stacks[0].Outputs[?OutputKey=='EnvironmentURL'].OutputValue" --output text
```

### Manual steps (without deploy.sh)

1. **Package the app:** `npm install && npm run package:eb` (produces `deploy.zip`).

2. **Upload the zip to S3** — from the **repo root**, use an existing bucket or create one with the optional bucket template:
   ```bash
   aws cloudformation create-stack --stack-name mock-service-artifacts \
     --template-body file://templates/mock-service/s3-artifacts-bucket.yaml \
     --parameters ParameterKey=BucketName,ParameterValue=mycompany-kyc-mock-artifacts
   aws s3 cp mock-service/deploy.zip s3://YOUR_BUCKET/mock-service/deploy.zip
   ```

3. **Create or update the CloudFormation stack** (from repo root):
   ```bash
   aws cloudformation create-stack --stack-name kyc-mock-service-eb \
     --template-body file://templates/mock-service/elastic-beanstalk.yaml \
     --parameters ParameterKey=S3Bucket,ParameterValue=YOUR_BUCKET ParameterKey=S3Key,ParameterValue=mock-service/deploy.zip
   ```
   Or use a parameters file: `--parameters file://templates/mock-service/parameters.example.json` (edit `S3Bucket`/`S3Key` first).

### Updating the app (new version)

1. `npm run package:eb` (rebuild and create a new `deploy.zip`).
2. Upload the new zip to S3 (same or new key, e.g. `mock-service/deploy-v2.zip`).
3. Update the stack with the new `S3Key` (and optionally a new key for the next version), or create a new ApplicationVersion in the console and deploy it to the existing environment.  
   For a simple “replace” flow, upload to the same key and run:
   ```bash
   aws cloudformation update-stack --stack-name kyc-mock-service-eb \
     --use-previous-template \
     --parameters ParameterKey=S3Bucket,UsePreviousValue=true ParameterKey=S3Key,UsePreviousValue=true
   ```
   Note: Changing only the zip content in S3 (without changing the key) does **not** trigger EB to redeploy. To redeploy the same key you need to create a new ApplicationVersion (e.g. via console: Upload new version) or use a new S3 key and update the stack’s `S3Key` parameter, then update the stack.

### Template parameters

| Parameter | Default | Description |
|-----------|--------|-------------|
| `ApplicationName` | kyc-mock-service | EB application name |
| `EnvironmentName` | mock-service-env | EB environment name |
| `SolutionStackName` | 64bit Amazon Linux 2023… Node.js 20 | Platform. List with: `aws elasticbeanstalk list-available-solution-stacks --query "SolutionStacks[?contains(@,'Node.js 20')]"` |
| `S3Bucket` | (required) | Bucket containing `deploy.zip` |
| `S3Key` | mock-service/deploy.zip | S3 key of the source bundle |
| `InstanceType` | t3.micro | EC2 instance type |
| `SeedDefaultTestCases` | 1 | Set to 0 to disable startup seeding |

The deployed zip must include `.ebextensions` (the packaging script does this) so the `data/` directory for SQLite is created on the instance.

---

## 4. What the templates do

### `.ebextensions/01_data_dir.config`

- Runs after the app is extracted on the instance.
- Creates a `data/` directory in the app folder and sets ownership to the `webapp` user so the Node process can write the SQLite file (`data/mock-data.db`).

### `.ebextensions/02_environment.config`

- Sets `NODE_ENV=production`.
- Optional: add `SEED_DEFAULT_TEST_CASES: "0"` under `aws:elasticbeanstalk:application:environment` to disable startup seeding of the four default test cases.

### `Procfile`

- Tells EB to run: `web: node dist/server.js`. EB sets the `PORT` environment variable; the app already listens on `process.env.PORT`.

### SQLite (simple, no EBS/EFS)

- The app writes the SQLite database to `data/mock-data.db` inside the deployment directory.
- The `.ebextensions` config ensures `data/` exists and is writable.
- Data is **ephemeral**: it is lost on redeploy or when the instance is replaced. The app seeds the default BRP and PEP test cases on every startup, so after each deploy you still have the same test keys.

### Reseeding test data (BRP + PEP)

To reseed the deployed mock (e.g. after adding new test cases or if startup seeding was disabled), from the **repo root** run:

```bash
./scripts/seed_mock_service_eb.sh
```

This script resolves the Elastic Beanstalk environment URL from the CloudFormation stack (`kyc-mock-service-eb` by default) and runs the seed script against it. To use a specific URL instead:

```bash
MOCK_SERVICE_URL=https://your-env.elasticbeanstalk.com ./scripts/seed_mock_service_eb.sh
```

Or from `mock-service/`: `MOCK_SERVICE_URL=https://your-env.elasticbeanstalk.com npm run seed`.

---

## 5. Useful commands

| Command | Description |
|--------|-------------|
| `eb status` | Environment name, health, CNAME |
| `eb open` | Open the app URL in the browser |
| `eb logs` | Fetch and open logs |
| `eb ssh` | SSH into the instance (if enabled) |
| `eb config` | Edit environment configuration |

---

## 6. Environment variables

Configure in the EB console (Configuration → Software → Environment properties) or via `.ebextensions`:

| Variable | Default | Description |
|----------|--------|-------------|
| `NODE_ENV` | Set to `production` by config | Environment |
| `PORT` | Set by EB | App listens on this port |
| `SEED_DEFAULT_TEST_CASES` | (not set = seed) | Set to `0` to disable startup seeding |

You do **not** need to set `MOCK_SERVICE_PORT`; the app uses `PORT` when it is set (by EB).
