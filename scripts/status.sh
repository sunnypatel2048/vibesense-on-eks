#!/usr/bin/env bash
# What's running right now: cluster, nodes, Argo CD apps, pods, queue depths.
#   make status
set -uo pipefail
source "$(dirname "$0")/lib.sh"

if ! cluster_exists; then
  echo "Cluster: not running (nothing billed per hour). make up to start it."
  exit 0
fi
echo "Cluster: $(aws eks describe-cluster --region "$REGION" --name "$CLUSTER" --query 'cluster.[status,version]' --output text | tr '\t' ' ')"
aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER" >/dev/null

printf '\nNodes\n'
kubectl get nodes -L vibesense/node-role,node.kubernetes.io/instance-type,karpenter.sh/capacity-type 2>/dev/null || echo "  (kubectl can't reach the cluster: is your IP in admin_cidrs?)"
printf '\nArgo CD apps\n'
kubectl -n argocd get applications 2>/dev/null
printf '\nVibeSense pods\n'
kubectl -n vibesense get pods 2>/dev/null

printf '\nQueues (waiting / in flight / DLQ)\n'
for q in ingest analysis aggregation notification; do
  url="$(aws sqs get-queue-url --region "$REGION" --queue-name "vibesense-$q" --query QueueUrl --output text 2>/dev/null)" || continue
  dlq="$(aws sqs get-queue-url --region "$REGION" --queue-name "vibesense-$q-dlq" --query QueueUrl --output text 2>/dev/null)"
  read -r waiting inflight < <(aws sqs get-queue-attributes --region "$REGION" --queue-url "$url" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes.[ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible]' --output text)
  dead="$(aws sqs get-queue-attributes --region "$REGION" --queue-url "$dlq" --attribute-names ApproximateNumberOfMessages \
    --query Attributes.ApproximateNumberOfMessages --output text)"
  printf '  %-13s %5s / %5s / %5s\n' "$q" "$waiting" "$inflight" "$dead"
done
