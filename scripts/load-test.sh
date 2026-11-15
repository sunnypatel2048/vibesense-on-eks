#!/usr/bin/env bash
# Run the load generator (src/load_test.py) inside the cluster as a one-off Job,
# and measure the whole run. Ends with a summary; nothing to read off by eye.
#
#   scripts/load-test.sh --jobs 20 --messages 200     (or: make load)
#   scripts/load-test.sh --cleanup                    (or: make load-clean)
#
# It reuses the ingestion worker's image, service account and database secret.
# That Pod Identity role may already send to the analysis queue, so the load
# test needs no new permissions, and it runs exactly the code that's deployed.
# The Job isn't in Git, so Argo CD leaves it alone; it deletes itself an hour
# after finishing.
#
# Set SKIP_SCALE_DOWN=1 to stop after the messages are processed instead of
# also timing the scale back to zero.
set -euo pipefail

NS=vibesense
image="$(kubectl -n "$NS" get deployment ingestion -o jsonpath='{.spec.template.spec.containers[0].image}')"
name="load-test-$(date +%H%M%S)"
if [[ $# -gt 0 ]]; then
  args="$(printf '%s\n' "$@" | jq -R . | jq -sc .)"
else
  args="[]"
fi
cleanup_only=false
[[ " $* " == *" --cleanup "* ]] && cleanup_only=true

tmp="$(mktemp -d)"
sampler_pid=""
trap '[[ -n "$sampler_pid" ]] && kill "$sampler_pid" 2>/dev/null; rm -rf "$tmp"' EXIT

# Every 5 s, note the AI worker's replica count and Karpenter's nodes.
sample() {
  while :; do
    kubectl -n "$NS" get deployment ai -o jsonpath='{.spec.replicas}{"\n"}' >>"$tmp/replicas" 2>/dev/null || true
    kubectl get nodeclaims -o jsonpath='{range .items[*]}{.metadata.name} {.metadata.labels.node\.kubernetes\.io/instance-type}{"\n"}{end}' \
      >>"$tmp/nodes" 2>/dev/null || true
    sleep 5
  done
}

# wait_for <timeout seconds> <command...>: retry every 5 s; returns 1 on timeout.
wait_for() {
  local deadline=$(( $(date +%s) + $1 )); shift
  until "$@"; do
    (( $(date +%s) >= deadline )) && return 1
    sleep 5
  done
}
ai_at_zero() { [[ "$(kubectl -n "$NS" get deployment ai -o jsonpath='{.spec.replicas}')" == "0" ]]; }
no_burst_nodes() { [[ -z "$(kubectl get nodeclaims -o name)" ]]; }
dlq_depth() {
  aws sqs get-queue-attributes --attribute-names ApproximateNumberOfMessages \
    --queue-url "$(aws sqs get-queue-url --queue-name "vibesense-$1-dlq" --query QueueUrl --output text)" \
    --query Attributes.ApproximateNumberOfMessages --output text
}

if ! $cleanup_only; then
  sample & sampler_pid=$!
fi

kubectl -n "$NS" apply -f - >/dev/null <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: $name
  labels:
    app.kubernetes.io/name: vibesense
    app.kubernetes.io/component: load-test
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app.kubernetes.io/name: vibesense
        app.kubernetes.io/component: load-test
    spec:
      restartPolicy: Never
      serviceAccountName: ingestion
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: load-test
          image: $image
          command: ["python", "-m", "src.load_test"]
          args: $args
          env:
            - name: AWS_REGION
              value: us-east-1
            - name: LOG_FORMAT
              value: console
            - name: DB_URL
              valueFrom:
                secretKeyRef:
                  name: vibesense-database
                  key: DB_URL
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              memory: 512Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
YAML
echo "Started Job $name"

kubectl -n "$NS" wait --for=condition=Ready pod -l job-name="$name" --timeout=120s >/dev/null 2>&1 || true
kubectl -n "$NS" logs -f "job/$name"
if ! kubectl -n "$NS" wait --for=condition=complete "job/$name" --timeout=30s >/dev/null 2>&1; then
  echo "The load test Job failed; see its output above." >&2
  exit 1
fi
$cleanup_only && exit 0

processed_at=$(date +%s)
scale_note="skipped (SKIP_SCALE_DOWN=1)"
nodes_note="skipped (SKIP_SCALE_DOWN=1)"
if [[ "${SKIP_SCALE_DOWN:-0}" != "1" ]]; then
  echo "Messages done. Timing the scale back down (AI pods to 0, then Karpenter removing its nodes)..."
  if wait_for 600 ai_at_zero; then scale_note="$(( $(date +%s) - processed_at ))s after the last message finished"; else scale_note="not within 10 min"; fi
  if wait_for 600 no_burst_nodes; then nodes_note="$(( $(date +%s) - processed_at ))s after the last message finished"; else nodes_note="not within 10 min"; fi
fi

kill "$sampler_pid" 2>/dev/null || true; sampler_pid=""
peak="$(sort -n "$tmp/replicas" 2>/dev/null | tail -1)"
nodes="$(awk 'NF == 2' "$tmp/nodes" 2>/dev/null | sort -u | awk '{print $2}' | sort | uniq -c | awk '{printf "%s%s × %s", sep, $1, $2; sep=", "}')"
node_count="$(awk 'NF == 2 {print $1}' "$tmp/nodes" 2>/dev/null | sort -u | wc -l | tr -d ' ')"

cat <<SUMMARY

================ Load test summary ================
Peak AI pods:         ${peak:-0}
Karpenter nodes:      ${node_count} (${nodes:-none})
AI pods back to 0:    ${scale_note}
Burst nodes removed:  ${nodes_note}
DLQ messages:         analysis $(dlq_depth analysis), aggregation $(dlq_depth aggregation), notification $(dlq_depth notification)
(The RESULT line above has the processing time and the lost/doubled check.)
===================================================
SUMMARY
