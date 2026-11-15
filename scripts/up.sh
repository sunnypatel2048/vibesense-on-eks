#!/usr/bin/env bash
# Bring the whole platform up from nothing: Terraform, kubeconfig, Argo CD, and
# a wait until every app is Synced and Healthy and the UI answers.
#
#   make up
#
# Safe to rerun: each step converges (terraform apply, helm upgrade --install).
set -euo pipefail
source "$(dirname "$0")/lib.sh"

step "Pre-flight checks"
aws sts get-caller-identity >/dev/null || fail "No AWS credentials."
[[ -f "$ROOT/infra/bootstrap/backend.hcl" ]] || fail "infra/bootstrap/backend.hcl is missing (see backend.hcl.example)."
[[ -f "$ROOT/infra/platform/terraform.tfvars" ]] || fail "infra/platform/terraform.tfvars is missing (see terraform.tfvars.example)."
# The EKS API only accepts admin_cidrs. A home IP changes now and then, and the
# symptom later (kubectl timing out) is confusing, so check it first.
my_ip="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
grep -q "\"$my_ip/32\"" "$ROOT/infra/platform/terraform.tfvars" \
  || fail "Your IP ($my_ip) isn't in admin_cidrs in infra/platform/terraform.tfvars. Update it (and the TF_VAR_ADMIN_CIDRS GitHub secret), then rerun."
secrets="$(aws ssm describe-parameters --region "$REGION" --parameter-filters Key=Path,Values=/vibesense/secrets --query 'length(Parameters)' --output text)"
(( secrets >= 4 )) || fail "Only $secrets of 4 app secrets exist in SSM. Run: make secrets"
note "AWS credentials, backend config, tfvars, your IP and app secrets: OK"

step "Terraform: platform layer (about 14 minutes)"
"${TF_PLATFORM[@]}" init -input=false -backend-config=../bootstrap/backend.hcl >/dev/null
"${TF_PLATFORM[@]}" apply -auto-approve -input=false
tf_done=$(elapsed)

step "kubeconfig"
aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER" >/dev/null
note "kubectl now points at $CLUSTER"

step "Argo CD and the root app"
"$ROOT/scripts/bootstrap-argocd.sh" >/dev/null
note "installed; the root app is syncing deploy/apps from main"

# Every Application in deploy/apps, plus root, plus the one the vibesense
# ApplicationSet generates.
expected=$(( $(grep -l '^kind: Application$' "$ROOT"/deploy/apps/*.yaml | wc -l) + 2 ))
step "Waiting for all $expected Argo CD apps to be Synced and Healthy"
not_ready() {
  kubectl -n argocd get applications -o json 2>/dev/null | jq -r --argjson n "$expected" '
    if (.items | length) < $n then "  (\(.items | length) of \($n) apps created so far)"
    else .items[] | select(.status.health.status != "Healthy" or .status.sync.status != "Synced")
      | "  \(.metadata.name): \(.status.sync.status // "?") / \(.status.health.status // "?")"
    end'
}
deadline=$(( $(date +%s) + 1200 ))
last=0
while :; do
  pending="$(not_ready || true)"
  [[ -z "$pending" ]] && break
  if (( $(date +%s) >= deadline )); then
    echo "$pending"
    fail "Not every app was ready after 20 minutes (above). Look at the first one in the Argo CD UI or: kubectl -n argocd describe application <name>"
  fi
  if (( $(date +%s) - last >= 60 )); then echo "$pending"; last=$(date +%s); fi
  sleep 10
done
apps_done=$(elapsed)
note "all $expected apps Synced and Healthy"

step "Waiting for the UI's load balancer"
addr=""
ui_up() {
  addr="$(kubectl -n vibesense get ingress ui -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)"
  [[ -n "$addr" ]] && [[ "$(curl -s -o /dev/null -w '%{http_code}' "http://$addr/_stcore/health")" == 200 ]]
}
wait_for 600 "the UI at its ALB" ui_up || fail "The UI didn't answer within 10 minutes. Check: kubectl -n vibesense get ingress,pods"

cat <<SUMMARY

================ make up: done in $(elapsed) ================
Terraform finished at:   $tf_done
All apps healthy at:     $apps_done
UI:                      http://$addr
Grafana:                 make grafana
Argo CD:                 kubectl -n argocd port-forward svc/argocd-server 8080:443  (https://localhost:8080)
Tear it all down:        make down
==============================================================
SUMMARY
