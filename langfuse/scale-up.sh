#!/usr/bin/env bash
# Bring the Langfuse demo stack back up after scale-down.sh.
#
#   1. Starts the Aurora PostgreSQL Serverless v2 cluster (waits until
#      available — takes a few minutes).
#   2. Restores every Deployment/StatefulSet in the `langfuse` namespace to
#      the replica counts recorded by scale-down.sh.
#   3. Reminds you that ClickHouse/ZooKeeper + Langfuse web have slow
#      startup probes (initialDelaySeconds: 300s), so give it ~5-10 min
#      before it's demo-ready.
#
# Usage: ./scale-up.sh

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-langfuse}"
NAMESPACE="${NAMESPACE:-langfuse}"
DB_CLUSTER_ID="${DB_CLUSTER_ID:-langfuse-postgres}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.demo-state"
STATE_FILE="${STATE_DIR}/replicas.txt"

echo "==> Checking Aurora cluster '${DB_CLUSTER_ID}' status"
DB_STATUS=$(aws rds describe-db-clusters \
  --db-cluster-identifier "${DB_CLUSTER_ID}" \
  --region "${AWS_REGION}" \
  --query 'DBClusters[0].Status' --output text)
echo "    current status: ${DB_STATUS}"

if [ "${DB_STATUS}" = "stopped" ]; then
  echo "==> Starting Aurora cluster '${DB_CLUSTER_ID}'"
  aws rds start-db-cluster --db-cluster-identifier "${DB_CLUSTER_ID}" --region "${AWS_REGION}" >/dev/null
  echo "==> Waiting for it to become available (this can take a few minutes)..."
  aws rds wait db-cluster-available --db-cluster-identifier "${DB_CLUSTER_ID}" --region "${AWS_REGION}"
  echo "    Aurora cluster is available."
else
  echo "    skipping start-db-cluster (not in 'stopped' state)"
fi

echo "==> Updating kubeconfig for EKS cluster '${CLUSTER_NAME}' (${AWS_REGION})"
aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${AWS_REGION}" >/dev/null

if [ ! -s "${STATE_FILE}" ]; then
  echo "!!  No saved replica state found at ${STATE_FILE}."
  echo "    Nothing to restore automatically — re-run 'terraform apply' or"
  echo "    'kubectl scale' the langfuse-web/langfuse-worker/clickhouse/zookeeper"
  echo "    workloads back up manually."
  exit 0
fi

echo "==> Restoring replica counts from ${STATE_FILE}"
while read -r kind name replicas; do
  [ -z "${name}" ] && continue
  echo "    ${kind}/${name} -> ${replicas}"
  kubectl scale "${kind}" "${name}" -n "${NAMESPACE}" --replicas="${replicas}"
done < "${STATE_FILE}"

echo "==> Done. Pods are starting."
echo "    ClickHouse/ZooKeeper migrations + Langfuse web probes have a"
echo "    300s initial delay — give it roughly 5-10 minutes before demoing."
echo "    Watch with: kubectl get pods -n ${NAMESPACE} -w"
