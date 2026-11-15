# VibeSense chart

Deploys the Streamlit UI, the four queue workers (ingestion, ai, aggregation,
notification), their secrets and the schema migration into the `vibesense`
namespace. Argo CD installs it through `deploy/apps/vibesense.yaml`.

## Order of a sync

| Wave | What | Why |
| --- | --- | --- |
| -1 | ExternalSecrets: `vibesense-database`, `vibesense-app-secrets`, `vibesense-platform` | Pods and the migration need them to start |
| 0 | `migrate` Job (`alembic upgrade head`), an Argo CD Sync hook | Pods refuse to run on an outdated schema |
| 1 | ServiceAccounts, Deployments, the UI Service and Ingress | |
| 2 | KEDA `TriggerAuthentication`, one `ScaledObject` per worker, the workers' `PodMonitor` | They refer to the Deployments from wave 1 |

A failed migration fails the sync, so a release never rolls out onto a schema
it can't use.

## Values that aren't in git

`registry` (contains the AWS account ID) and `ingress.allowedCidrs` (your IP)
come from Terraform via Argo CD's cluster record; see
`scripts/bootstrap-argocd.sh`. The chart refuses to render without them. To
render it locally: `make lint-chart`.

## Autoscaling

KEDA scales each worker on its SQS queue's depth, counting messages waiting and
in flight: replicas = messages / `queueLength`, within the worker's bounds.

| Worker | Queue | Replicas | Messages per replica |
| --- | --- | --- | --- |
| ai | analysis | 0–6 | 5 |
| ingestion | ingest | 1–3 | 2 |
| aggregation | aggregation | 1–3 | 10 |
| notification | notification | 1–3 | 10 |

The AI worker scales to zero after 2 idle minutes, since the model's memory is
the largest cost; the light workers stay warm. Queue depth rather than CPU,
because a worker waiting on the YouTube API or SMTP shows low CPU while its
backlog grows. The Deployments of autoscaled workers have no `replicas` field,
so Argo CD never fights KEDA over it.

## Network policies

Incoming traffic is denied by default. Two exceptions: the UI's port (8501),
which the ALB forwards to, and the workers' metrics port (9000), only from
Prometheus in the `monitoring` namespace. A compromised pod elsewhere in the
cluster can't reach the workers.

Outgoing traffic is not restricted. The workers call AWS APIs, the YouTube API
and Gmail SMTP, and a NetworkPolicy filters by IP address, not domain name;
those services' IPs change and are shared with much of the internet, so an IP
allow-list would be either brittle or meaningless. The production answer is an
egress proxy or a CNI that filters by DNS name (for example Cilium's FQDN
policies), plus VPC endpoints so AWS traffic never leaves the VPC. Both cost
more than this project's budget.

## Why the UI runs one replica

Streamlit keeps each user's session in the memory of one pod and talks to the
browser over a WebSocket. With two replicas, the ALB could send a reconnect to
the other pod, which knows nothing about that session, and the page resets. To
scale it out: turn on ALB sticky sessions (`stickiness.enabled=true` in the
target group attributes annotation) so each browser stays on one pod, add a
PodDisruptionBudget, and accept that a pod restart still drops the sessions on
that pod. For this project, one replica is enough; all heavy work happens in
the queue workers, which scale independently.
