#!/usr/bin/env bash
# Install Argo CD and hand the cluster to Git. The only imperative step after
# `terraform apply`: everything else is installed by Argo CD from deploy/apps/.
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

echo "==> Installing Argo CD (chart $CHART_VERSION)"
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update argo >/dev/null
helm upgrade --install argocd argo/argo-cd \
  --version "$CHART_VERSION" \
  --namespace argocd --create-namespace \
  --values "$ROOT/deploy/platform/argocd-values.yaml" \
  --wait --timeout 10m

echo "==> Handing the cluster to Git (root app -> deploy/apps on main)"
kubectl apply -f "$ROOT/deploy/root-app.yaml"

cat <<MSG

Argo CD is running. To open the UI:
  kubectl -n argocd port-forward svc/argocd-server 8080:443
  open https://localhost:8080        (user: admin; self-signed certificate)

Initial admin password:
  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
MSG
