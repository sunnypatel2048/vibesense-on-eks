# Measurements

Numbers measured on real runs, for the README and for sizing decisions.
Re-measure when something here changes; keep the date.

## Platform lifecycle (us-east-1, EKS 1.37, 2x Spot Graviton system nodes)

| What | Time | Measured | Notes |
| --- | --- | --- | --- |
| `terraform apply` (infra/platform, ~105 resources with Karpenter) | 13–15 min | 2026-11-14: 14 m 49 s, 12 m 52 s; 2026-11-15: 14 m 13 s | EKS control plane and RDS dominate |
| `make argocd` → every Argo CD app Synced/Healthy | 3 m 30 s | 2026-11-14: 210 s | 5 apps: root, metrics-server, aws-load-balancer-controller, external-secrets, cluster-config. Wave 1 waits for wave 0 to be Healthy |
| Same, full platform | 5 m 18 s | 2026-11-15: 318 s | 9 apps in waves −1 to 3, including cert-manager, KEDA, Karpenter and the app |
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

## Delivery and autoscaling on EKS (2026-11-15, Phase 8 session)

| What | Result |
| --- | --- |
| Merge to `main` → new pods Ready, no `kubectl` | 261 s (release build and push, tag bump, Argo CD sync, rollout) |
| Network policy: another pod → a worker's port 9000 | Blocked; all pods stayed Ready |

Load test: 200 analysis messages × 50 comments (`make load JOBS=20 MESSAGES=200`), AI worker starting at 0 pods.

| What | Result |
| --- | --- |
| Messages sent → KEDA creates the first AI pod | ≤ 6 s (polling every 10 s) |
| Karpenter NodeClaim created → node Ready | 38–62 s (3 nodes: 1 × c7g.medium, 2 × t4g.medium, all Spot) |
| Messages sent → first AI pod Ready (scale-from-zero cold start) | 87 s: ~40 s node, ~26 s image pull, ~19 s model load and first poll |
| Peak AI pods | 6 (the maximum), 2 per node |
| Draining 200 messages (10,000 comments) once pods were up | ~2 min; 3.5 min from first message sent |
| Queue empty → AI pods scaled to zero | 1 m 44 s (cooldown 120 s) |

Karpenter launched three small nodes rather than one larger one because KEDA
added pods in steps (1, then 4, then 6) and Karpenter provisions each batch of
pending pods as it sees them.
