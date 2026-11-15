# Measurements

Numbers measured on real runs, for the README and for sizing decisions.
Re-measure when something here changes; keep the date.

## Platform lifecycle (us-east-1, EKS 1.37, 2x Spot Graviton system nodes)

| What | Time | Measured | Notes |
| --- | --- | --- | --- |
| `terraform apply` (infra/platform, ~94 resources) | 13–15 min | 2026-11-14: 14 m 49 s, 12 m 52 s | EKS control plane and RDS dominate |
| `make argocd` → every Argo CD app Synced/Healthy | 3 m 30 s | 2026-11-14: 210 s | 5 apps: root, metrics-server, aws-load-balancer-controller, external-secrets, cluster-config. Wave 1 waits for wave 0 to be Healthy |
| `terraform destroy` | ~12 min | 2026-11-14: 12 m 14 s | |
| Running cost while up | ~$0.19/hour | | Torn down after every session |

![Argo CD root app with the platform add-ons](images/argocd-root-app.png)

## Images and the AI service

| What | Value | Notes |
| --- | --- | --- |
| `app` image | 1.35 GB | Streamlit UI and the pipeline workers |
| `ai` image | 2.43 GB (~790 MB compressed in ECR) | CPU-only PyTorch, model baked in at a pinned revision |
| AI worker restart → healthy | < 10 s | Model loads from the image, no download (local compose) |
| Job created → first email | 1–2 s | Local compose with Mailpit |

## End to end on EKS (2026-11-14, Task 6.4)

| What | Result |
| --- | --- |
| Demo job submitted through the ALB → email in a real inbox | 2–3 s |
| Malformed message on the analysis queue → DLQ | After 5 attempts (retries at 10, 30, 90, 270 s) |
| DLQ → alarm email (CloudWatch → SNS) | Arrived |

`kubectl top pods -n vibesense` during the demo job, used to size the chart's
requests:

| Pod | CPU | Memory |
| --- | --- | --- |
| ai | 2m | 390Mi |
| ingestion | 1m | 170Mi |
| ui | 6m | 129Mi |
| notification | 1m | 79Mi |
| aggregation | 1m | 77Mi |
