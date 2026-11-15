#!/usr/bin/env bash
# Spot interruption drill (Task 8.5), measured end to end:
#   1. starts a load test (200 messages) in the background
#   2. waits until a burst node runs at least 2 AI pods mid-load
#   3. drains that node, as Karpenter does on a Spot interruption notice
#   4. times how long until every AI pod is Ready again, and which new node
#      Karpenter launched for them
#   5. waits for the load test's own check that every message was processed
#      exactly once, and prints both summaries
#
#   scripts/drain-drill.sh     (or: make drill)
set -euo pipefail

NS=vibesense
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
log="$(mktemp)"

echo "Starting the load test in the background (output: $log)"
SKIP_SCALE_DOWN=1 "$ROOT/scripts/load-test.sh" --jobs 10 --messages 200 >"$log" 2>&1 &
load_pid=$!

# A burst node with at least 2 Running AI pods: draining it must move real work.
echo "Waiting for a burst node with 2+ AI pods running..."
node=""
deadline=$(( $(date +%s) + 600 ))
until [[ -n "$node" ]]; do
  (( $(date +%s) >= deadline )) && { echo "No burst node with 2 AI pods within 10 min." >&2; exit 1; }
  sleep 5
  node="$(kubectl -n "$NS" get pods -l app.kubernetes.io/component=ai --field-selector=status.phase=Running \
    -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort | uniq -c | awk '$1 >= 2 {print $2; exit}' || true)"
done
moved="$(kubectl -n "$NS" get pods -l app.kubernetes.io/component=ai --field-selector=spec.nodeName="$node" -o name | wc -l | tr -d ' ')"
claims_before="$(kubectl get nodeclaims -o name | sort)"

echo "Draining $node ($moved AI pods on it)"
t0=$(date +%s)
kubectl drain "$node" --ignore-daemonsets --delete-emptydir-data --timeout=5m >/dev/null
evicted=$(( $(date +%s) - t0 ))

# Recovered = no AI pod is waiting (Pending or still starting) and all are Ready.
all_ready() {
  local pods total ready
  pods="$(kubectl -n "$NS" get pods -l app.kubernetes.io/component=ai --no-headers 2>/dev/null | grep -v Terminating || true)"
  total="$(grep -c . <<<"$pods" || true)"
  ready="$(awk '$2 == "1/1" && $3 == "Running"' <<<"$pods" | grep -c . || true)"
  [[ "$total" -gt 0 && "$total" == "$ready" ]]
}
until all_ready; do
  (( $(date +%s) - t0 > 600 )) && { echo "AI pods not all Ready within 10 min of the drain." >&2; break; }
  sleep 5
done
recovered=$(( $(date +%s) - t0 ))
new_nodes="$(comm -13 <(echo "$claims_before") <(kubectl get nodeclaims -o name | sort) | while read -r c; do
  kubectl get "$c" -o jsonpath='{.metadata.labels.node\.kubernetes\.io/instance-type}{" "}'; done)"

echo "Drain measured. Waiting for the load test to finish its own check..."
wait "$load_pid" || true
cat <<SUMMARY

================ Drain drill summary ================
Drained node:          $node ($moved AI pods moved)
Eviction finished in:  ${evicted}s
All AI pods Ready in:  ${recovered}s after the drain started
New Karpenter nodes:   ${new_nodes:-none (the pods fit on existing nodes)}
=====================================================
SUMMARY
grep -E '^RESULT' "$log" || { echo "No RESULT line from the load test; its output:"; cat "$log"; }
grep -A8 'Load test summary' "$log" | grep -E 'DLQ|Peak|Karpenter nodes' || true
rm -f "$log"
echo "The drained node stays cordoned until Karpenter removes it (it's empty, so within a few minutes)."
