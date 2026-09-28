#!/usr/bin/env bash
# Scale the Langfuse demo stack down to (near) zero cost without destroying it.
#
# What this does:
#   1. Records current replica counts for every Deployment/StatefulSet in the
#      `langfuse` namespace (so scale-up.sh can restore them exactly).
#   2. Scales all of them to 0 replicas -> Fargate stops billing for compute
#      immediately (no idle charge for pods that don't exist).
#   3. Stops the Aurora PostgreSQL Serverless v2 cluster -> no ACU billing
#      while stopped (auto-resumes after 7 days if you don't start it first).
#
# What keeps running (and costing money) after this script:
#   - EKS control plane (~$0.10/hr flat, no stop mechanism short of deleting
#     the cluster).
#   - ElastiCache Redis (no stop mechanism; left running since deleting it
#     means re-provisioning + losing the auth token wiring on scale-up).
#   - EFS storage (pay-per-GB, negligible).
#
# Usage: ./scale-down.sh

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-langfuse}"
NAMESPACE="${NAMESPACE:-langfuse}"
DB_CLUSTER_ID="${DB_CLUSTER_ID:-langfuse-postgres}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.demo-state"
STATE_FILE="${STATE_DIR}/replicas.txt"

echo "==> Updating kubeconfig for EKS cluster '${CLUSTER_NAME}' (${AWS_REGION})"
aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${AWS_REGION}" >/dev/null

mkdir -p "${STATE_DIR}"

echo "==> Recording current replica counts to ${STATE_FILE}"
: > "${STATE_FILE}"
for kind in deployment statefulset; do
  while read -r name replicas; do
    [ -z "${name}" ] && continue
    echo "${kind} ${name} ${replicas}" >> "${STATE_FILE}"
  done < <(kubectl get "${kind}" -n "${NAMESPACE}" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.replicas}{"\n"}{end}')
done

if [ ! -s "${STATE_FILE}" ]; then
  echo "    No Deployments/StatefulSets found in namespace '${NAMESPACE}' — nothing to scale down there."
else
  cat "${STATE_FILE}"
fi

echo "==> Scaling all Deployments and StatefulSets in '${NAMESPACE}' to 0 replicas"
kubectl get deployment -n "${NAMESPACE}" -o name | xargs -r -n1 kubectl scale -n "${NAMESPACE}" --replicas=0
kubectl get statefulset -n "${NAMESPACE}" -o name | xargs -r -n1 kubectl scale -n "${NAMESPACE}" --replicas=0

echo "==> Checking Aurora cluster '${DB_CLUSTER_ID}' status"
DB_STATUS=$(aws rds describe-db-clusters \
  --db-cluster-identifier "${DB_CLUSTER_ID}" \
  --region "${AWS_REGION}" \
  --query 'DBClusters[0].Status' --output text)
echo "    current status: ${DB_STATUS}"

if [ "${DB_STATUS}" = "available" ]; then
  echo "==> Stopping Aurora cluster '${DB_CLUSTER_ID}' (auto-resumes after 7 days if left stopped)"
  aws rds stop-db-cluster --db-cluster-identifier "${DB_CLUSTER_ID}" --region "${AWS_REGION}" >/dev/null
else
  echo "    skipping stop-db-cluster (not in 'available' state)"
fi

echo "==> Done."
echo "    Still billing: EKS control plane (~\$0.10/hr) + ElastiCache Redis."
echo "    Run ./scale-up.sh before your next demo."
