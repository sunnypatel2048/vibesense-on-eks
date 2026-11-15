#!/usr/bin/env bash
# Install Argo CD and hand the cluster to Git. The only imperative step after
# `terraform apply`: everything else is installed by Argo CD from deploy/apps/.
#
# It also registers this cluster with Argo CD, carrying the Terraform outputs
# the app needs but that must stay out of git (the ECR registry, which contains
# the account ID, and the CIDRs allowed to reach the UI). This is the "GitOps
# Bridge" pattern; deploy/apps/vibesense.yaml reads them.
#
#   scripts/bootstrap-argocd.sh      (or: make argocd)
set -euo pipefail

CHART_VERSION="10.18.0" # argo/argo-cd; bump deliberately (helm search repo argo/argo-cd)
CLUSTER="vibesense"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Refuse to install into the wrong cluster.
context="$(kubectl config current-context)"
if [[ "$context" != *"cluster/$CLUSTER" ]]; then
  echo "kubectl is pointed at '$context', not the $CLUSTER cluster." >&2
  echo "Run: aws eks update-kubeconfig --region us-east-1 --name $CLUSTER" >&2
  exit 1
fi

echo "==> Reading Terraform outputs for Argo CD"
metadata="$(terraform -chdir="$ROOT/infra/platform" output -json gitops_metadata)" || {
  echo "No gitops_metadata output. Run terraform apply in infra/platform first." >&2
  exit 1
}
aws_account_id="$(jq -r '.aws_account_id' <<<"$metadata")"
ecr_registry="$(jq -r '.ecr_registry' <<<"$metadata")"
ui_allowed_cidrs="$(jq -r '.ui_allowed_cidrs' <<<"$metadata")"

echo "==> Installing Argo CD (chart $CHART_VERSION)"
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update argo >/dev/null
helm upgrade --install argocd argo/argo-cd \
  --version "$CHART_VERSION" \
  --namespace argocd --create-namespace \
  --values "$ROOT/deploy/platform/argocd-values.yaml" \
  --wait --timeout 10m

echo "==> Registering the cluster with Argo CD (labels and annotations for ApplicationSets)"
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: in-cluster
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    vibesense.io/workloads: "true"
  annotations:
    vibesense.io/aws-account-id: "$aws_account_id"
    vibesense.io/ecr-registry: "$ecr_registry"
    vibesense.io/ui-allowed-cidrs: "$ui_allowed_cidrs"
type: Opaque
stringData:
  name: in-cluster
  server: https://kubernetes.default.svc
  config: '{"tlsClientConfig":{"insecure":false}}'
EOF

echo "==> Handing the cluster to Git (root app -> deploy/apps on main)"
kubectl apply -f "$ROOT/deploy/root-app.yaml"

cat <<MSG

Argo CD is running. To open the UI:
  kubectl -n argocd port-forward svc/argocd-server 8080:443
  open https://localhost:8080        (user: admin; self-signed certificate)

Initial admin password:
  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
MSG
