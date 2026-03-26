Vendored chart: copied from https://github.com/langfuse/langfuse-k8s (git tag langfuse-1.5.14; app/chart version in charts/langfuse/Chart.yaml).

Bitnami subcharts (postgresql, clickhouse, redis, minio, common) are not stored in git. Either:
  - Run: cd langfuse/charts/langfuse && helm dependency build
  - Or run terraform apply: helm_release uses dependency_update = true (needs Helm installed + network to oci://registry-1.docker.io/bitnamicharts).

To refresh the vendored main chart from upstream, re-clone or helm pull that tag and replace charts/langfuse (keeping templates/values).
