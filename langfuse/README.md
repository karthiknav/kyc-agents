# Langfuse Deployment

## Prerequisites: AWS Resources

The following AWS resources must exist **before** running `terraform init` or `terraform apply`. They are created by the KYC CloudFormation stacks and are not managed by this Terraform module.

### S3 State Bucket

Terraform remote state is stored in the existing artifacts bucket:

```
kyc-agent-artifacts-360946915124-us-east-1
```

This bucket is created by `templates/base/storage-stack.yaml` (`ArtifactsBucket`). State is stored at the key `langfuse/terraform.tfstate`.

### VPC & Subnets

The `main.tf` references a pre-existing VPC and subnets (created outside this module):

| Resource | ID |
|---|---|
| VPC | `vpc-0471d506bfc76f3d9` |
| Private Subnet 1 | `subnet-093a6535e084d1b87` |
| Private Subnet 2 | `subnet-0bc3915284f4d7cae` |
| Public Subnet 1 | `subnet-0047a37be8d0a9a6d` |
| Public Subnet 2 | `subnet-0ff49bee49396da89` |
| Private Route Table | `rtb-040d1056d5cab6969` |

### EC2 Instance IAM Role (for running from EC2 Instance Connect)

If running Terraform from an EC2 instance, the instance's IAM role must have the following permissions on the state bucket:

```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::kyc-agent-artifacts-360946915124-us-east-1",
    "arn:aws:s3:::kyc-agent-artifacts-360946915124-us-east-1/*"
  ]
}
```

### Optional: EC2 Instance Connect (for running kubectl/Terraform from a private-subnet EC2 instance)

The VPC/subnets above are private — there's no public endpoint to reach the EKS cluster or run Terraform against it from outside the VPC. To run `kubectl`/`terraform` from a private-subnet EC2 instance, connect via [EC2 Instance Connect](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-connect.html) instead of opening SSH to the internet.

1. **Launch the instance** in `Private Subnet 1`/`Private Subnet 2` above, with the IAM role from [EC2 Instance IAM Role](#ec2-instance-iam-role-for-running-from-ec2-instance-connect) attached.
2. **Create an EC2 Instance Connect Endpoint** in the same VPC, if one doesn't already exist:

   ```bash
   aws ec2 create-instance-connect-endpoint \
     --subnet-id subnet-093a6535e084d1b87 \
     --security-group-ids <SecurityGroupId> \
     --region us-east-1
   ```

3. **Connect** — no public IP, no SSH key distribution, no `0.0.0.0/0` NACL/SG rule needed:

   ```bash
   aws ec2-instance-connect ssh --instance-id <InstanceId> --region us-east-1
   ```

4. **Install Terraform/kubectl/helm** (see sections below) and run the deployment steps from there.

Because the connection originates from the Instance Connect Endpoint's ENI inside the VPC, this requires no NACL changes — see [NACL-COMPLIANCE.md](../NACL-COMPLIANCE.md) for how the private-subnet NACL already permits intra-VPC traffic. Terminate the instance when you're done; it isn't part of the standing infrastructure.

---

## Prerequisite: Install Helm

Helm is required to download the chart dependencies (postgresql, clickhouse, valkey, minio, common) before Terraform can deploy Langfuse.

### macOS (Homebrew)
```bash
brew install helm
```

### Linux / AWS CloudShell
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### Windows
Download the latest release from the [Helm releases page](https://github.com/helm/helm/releases/latest), unzip, and add `helm.exe` to your PATH.

Verify installation:
```bash
helm version
```

---

## Prerequisite: Install kubectl

### Linux
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
```

### macOS (Homebrew)
```bash
brew install kubectl
```

### Windows
```powershell
winget install -e --id Kubernetes.kubectl
```

Verify installation:
```bash
kubectl version --client
```

---

## Prerequisite: Install Terraform

You need **Terraform >= 1.9.0** installed. The module uses cross-variable references in validation blocks, which were introduced in 1.9. Earlier versions (including the default on AWS CloudShell) will fail on `terraform init`.

### macOS (Homebrew)
```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

### Linux / AWS CloudShell
```bash
LATEST=$(curl -s https://checkpoint-api.hashicorp.com/v1/check/terraform | python3 -c "import sys,json; print(json.load(sys.stdin)['current_version'])")
wget https://releases.hashicorp.com/terraform/${LATEST}/terraform_${LATEST}_linux_amd64.zip
unzip terraform_${LATEST}_linux_amd64.zip
mkdir -p ~/bin
mv terraform ~/bin/
export PATH="$HOME/bin:$PATH"   # add to ~/.bashrc to persist in CloudShell
```

### Windows
Download the latest Terraform release from the [official downloads page](https://developer.hashicorp.com/terraform/install#windows), unzip, and add the executable to your PATH.

Verify installation:
```bash
terraform version  # must be >= 1.9.0
```


## Deployment Steps

### 1. Apply the DNS zone

```bash
terraform init
terraform apply --target module.langfuse.aws_route53_zone.zone
```

### 2. Set up Nameserver delegation

Take the NS records from the newly created hosted zone and add them to your DNS provider for the subdomain. You can retrieve them with:
Checkout Domain.md

```bash
dig NS langfuse.example.com
```

Example output:
```
ns-1.awsdns-00.org.
ns-2.awsdns-01.net.
ns-3.awsdns-02.com.
ns-4.awsdns-03.co.uk.
```

Add these as NS records in your parent domain's DNS provider. See [DOMAIN.md](DOMAIN.md) for details on cross-account NS delegation.


### 3. Update Terraform configuration (if needed)

Before applying the full stack, open `main.tf` and update the domain name, VPC ID, and subnet IDs as required for your environment.

### 4. Pull Helm chart dependencies

Download the required sub-charts (postgresql, clickhouse, valkey, minio, common) into the `charts/` directory. This must be done before `terraform apply` — Terraform's `helm_release` resource expects the dependencies to already be present locally.

```bash
helm dependency update langfuse/charts/langfuse
```

### 5. Apply the full stack

```bash
terraform apply
```

If this fails, run through the commands under [Known Issues](#known-issues) below, then re-run `terraform apply`.

---

## Known Issues

### CoreDNS / ClickHouse pods fail on initial creation

Due to a race condition between the Fargate Profile creation and Kubernetes pod scheduling, on the initial deployment the CoreDNS and ClickHouse containers must be restarted manually.

```bash
# Connect kubectl to the EKS cluster
aws eks update-kubeconfig --name langfuse

# Restart CoreDNS and ClickHouse containers
kubectl --namespace kube-system rollout restart deploy coredns
kubectl --namespace langfuse delete pod langfuse-clickhouse-shard0-{0,1,2} langfuse-zookeeper-{0,1,2}
```

Then re-run `terraform apply`.

### Scale the web deployment

After `terraform apply` completes and the ClickHouse/CoreDNS pods are running, scale up the web deployment, as the inial deployment started with 0 replicas for web:

```bash
kubectl scale deployment langfuse-web -n langfuse --replicas=1
```

Check the logs to verify the web pod started successfully:
```bash
kubectl logs <web-pod-name> -n langfuse --tail=200
```

Get the pod name with:
```bash
kubectl get pods -n langfuse
```

### Helm release timeout on destroy

If `terraform apply` fails with `uninstallation completed with 1 error(s): context deadline exceeded`, Kubernetes resources (ClickHouse/ZooKeeper pods and PVCs) did not terminate within Helm's default 5-minute timeout.

Check pod and PVC state:
```bash
kubectl get pods -n langfuse
kubectl get pvc -n langfuse
```

If pods are gone but PVCs remain, delete them manually:
```bash
kubectl delete pvc -n langfuse \
  data-langfuse-clickhouse-shard0-0 \
  data-langfuse-clickhouse-shard0-1 \
  data-langfuse-clickhouse-shard0-2 \
  data-langfuse-zookeeper-0 \
  data-langfuse-zookeeper-1 \
  data-langfuse-zookeeper-2
```

If any PVC gets stuck deleting, strip its finalizer:
```bash
for pvc in data-langfuse-clickhouse-shard0-0 data-langfuse-clickhouse-shard0-1 data-langfuse-clickhouse-shard0-2 data-langfuse-zookeeper-0 data-langfuse-zookeeper-1 data-langfuse-zookeeper-2; do
  kubectl patch pvc $pvc -n langfuse -p '{"metadata":{"finalizers":null}}'
done
```

If the namespace itself is stuck, delete it to force cleanup:
```bash
kubectl delete namespace langfuse
```

Then re-run `terraform apply`.

### Pod stuck in Pending state

If a pod remains in `Pending` for a long time, describe it to see the scheduling events and error reason:
```bash
kubectl describe pod langfuse-clickhouse-shard0-0 -n langfuse
```

Common causes are insufficient Fargate resources, missing node selectors, or PVC binding failures. Check the `Events` section at the bottom of the output for details.

### Ingress not created after Helm release timeout

If `terraform apply` times out during the Helm release (e.g. due to ClickHouse/ZooKeeper taking too long on first boot), the ingress may not get created even though all pods are running. You can apply it directly without re-running Terraform:

```bash
kubectl get ingress -A
```

If no ingress is listed, apply it directly:

```bash
kubectl apply -f ingress.yaml
```

This creates the ALB-backed ingress for `langfuse.noonehasthisdomain.click` without touching any other resources.

### ClickHouse schema migration failure

**Error:** `Applying clickhouse migrations failed. This is mostly caused by the database being unavailable.`

This happens when a previous migration run left the `schema_migrations` table in a dirty state. Fix it by resetting the dirty flag directly in ClickHouse.

First, retrieve the ClickHouse admin password from the pod's environment:
```bash
kubectl exec -n langfuse langfuse-clickhouse-shard0-0 -- printenv | grep CLICKHOUSE_ADMIN_PASSWORD
```

Then use the password to reset the dirty migration:
```bash
kubectl exec -n langfuse langfuse-clickhouse-shard0-0 -- \
  clickhouse-client \
  --user="default" \
  --password="<CLICKHOUSE_ADMIN_PASSWORD>" \
  --query "ALTER TABLE schema_migrations UPDATE dirty = 0 WHERE dirty = 1"
```

Finally, restart the web deployment to re-trigger the migration:
```bash
kubectl rollout restart deployment langfuse-web -n langfuse
```

# Troubleshooting

## Restart worker or web without Terraform

If the worker or web pod needs to be restarted (e.g. after a NACL change, config update, or connection failure) without running `terraform apply`:

```bash
kubectl --namespace langfuse rollout restart deployment langfuse-worker
kubectl --namespace langfuse rollout restart deployment langfuse-web
```

Watch the new pod come up and stream its logs:

```bash
# Watch pod status until Running
kubectl --namespace langfuse get pods -w

# Stream logs from the worker (replace <pod-name> with the new pod name from above)
kubectl --namespace langfuse logs -f <pod-name>

# Or follow logs without knowing the pod name yet
kubectl --namespace langfuse logs -f -l app.kubernetes.io/component=worker --since=1m
```

## Ingress not created / ALB not provisioned

Check whether the ingress resource exists and whether the ALB Controller has provisioned it:

```bash
# Check if the ingress resource exists and has an ALB address assigned
kubectl --namespace langfuse get ingress

# If ADDRESS is empty, the ALB hasn't been provisioned yet — describe to see events
kubectl --namespace langfuse describe ingress langfuse

# Check the ALB controller logs for errors
kubectl --namespace kube-system logs -l app.kubernetes.io/name=aws-load-balancer-controller --tail=50
```

If the ingress resource is missing entirely (e.g. after a Helm timeout), apply it manually from the repo:

```bash
kubectl apply -f langfuse/ingress.yaml
```

After applying, watch the `ADDRESS` field populate as the ALB is provisioned (takes ~1-2 minutes):

```bash
kubectl --namespace langfuse get ingress -w
```

Once the address appears, that's the ALB DNS name. Your domain (`langfuse.gen-ai-designs.com`) should already point to it via Route 53.

## Helm dependency error

If you see an error like:

```
Error: found in Chart.yaml, but missing in charts/ directory: postgresql, clickhouse, valkey, minio, common
```

This means the required Helm chart dependencies listed in `Chart.yaml` are missing from the `charts/` directory.

**Resolution:**

If `helm` is not installed (e.g. on an EC2 instance), install it first:

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Then download the chart dependencies:

```bash
helm dependency update langfuse/charts/langfuse
```

This will download the required dependencies into the `charts/` directory. After this, re-run `terraform apply`.

---
