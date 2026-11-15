# Shared helpers for scripts/up.sh, down.sh and leftovers.sh. Source, don't run.

REGION="${AWS_REGION:-us-east-1}"
CLUSTER=vibesense
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_PLATFORM=(terraform -chdir="$ROOT/infra/platform")
_started=$(date +%s)

elapsed() { local s=$(( $(date +%s) - _started )); printf '%dm%02ds' $((s / 60)) $((s % 60)); }
step() { printf '\n==> [%s] %s\n' "$(elapsed)" "$*"; }
note() { printf '    %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# wait_for <timeout seconds> <description> <command...>: retry every 10 s.
wait_for() {
  local timeout=$1 what=$2; shift 2
  local deadline=$(( $(date +%s) + timeout ))
  until "$@" >/dev/null 2>&1; do
    (( $(date +%s) >= deadline )) && { note "timed out after ${timeout}s waiting for: $what"; return 1; }
    sleep 10
  done
}

cluster_exists() { aws eks describe-cluster --region "$REGION" --name "$CLUSTER" >/dev/null 2>&1; }
