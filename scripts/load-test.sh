#!/usr/bin/env bash
# Run the load generator (src/load_test.py) inside the cluster as a one-off Job,
# and follow its output.
#
#   scripts/load-test.sh --jobs 20 --messages 200     (or: make load)
#   scripts/load-test.sh --cleanup                    (or: make load-clean)
#
# It reuses the ingestion worker's image, service account and database secret.
# That Pod Identity role may already send to the analysis queue, so the load
# test needs no new permissions, and it runs exactly the code that's deployed.
# The Job isn't in Git, so Argo CD leaves it alone; it deletes itself an hour
# after finishing.
set -euo pipefail

NS=vibesense
image="$(kubectl -n "$NS" get deployment ingestion -o jsonpath='{.spec.template.spec.containers[0].image}')"
name="load-test-$(date +%H%M%S)"
if [[ $# -gt 0 ]]; then
  args="$(printf '%s\n' "$@" | jq -R . | jq -sc .)"
else
  args="[]"
fi

kubectl -n "$NS" apply -f - <<YAML
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

kubectl -n "$NS" wait --for=condition=Ready pod -l job-name="$name" --timeout=120s >/dev/null 2>&1 || true
kubectl -n "$NS" logs -f "job/$name"
kubectl -n "$NS" wait --for=condition=complete "job/$name" --timeout=60s
