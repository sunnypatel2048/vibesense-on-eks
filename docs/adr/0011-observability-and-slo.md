# ADR-0011: In-cluster Prometheus and Grafana, and a 5-minute latency SLO

**Status:** Accepted

## Context

The demo needs a dashboard that tells the whole story of a load test, an objective with an alert, and searchable logs, all destroyed with the cluster.

## Decision

kube-prometheus-stack (6 hours of metrics on `emptyDir`, no persistent volumes), with the Prometheus Operator's CRDs installed first in their own app. One Grafana dashboard lives in Git as JSON. The objective: **95% of intervals are notified within 5 minutes of their comments entering the pipeline**, measured by a histogram the notification worker records from an `enqueued_at` stamp; the alert fires when p95 stays above 5 minutes for 10 minutes and reaches email through Alertmanager → SNS. Fluent Bit ships the app's JSON logs to CloudWatch Logs with 1-day retention.

## Consequences

- Nothing extra to pay for or clean up; dashboards and rules survive teardown because they're in Git.
- 5 minutes, not 2: a scale-from-zero cold start alone is about 90 s. A tighter target means paying for warm capacity; the business chooses the target, then pays for it.
- Measured 99.4–100% within target across load tests and a drain drill.

## Alternatives considered

Amazon Managed Service for Prometheus and Managed Grafana (the production choice, with a standing cost); CloudWatch Container Insights (per-metric charges, less flexible dashboards).
