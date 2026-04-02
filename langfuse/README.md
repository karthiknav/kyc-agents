# Langfuse Deployment

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

### 3. Apply the full stack

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
