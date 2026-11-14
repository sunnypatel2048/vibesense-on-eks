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

A failed migration fails the sync, so a release never rolls out onto a schema
it can't use.

## Values that aren't in git

`registry` (contains the AWS account ID) and `ingress.allowedCidrs` (your IP)
come from Terraform via Argo CD's cluster record; see
`scripts/bootstrap-argocd.sh`. The chart refuses to render without them. To
render it locally: `make lint-chart`.

## Why the UI runs one replica

Streamlit keeps each user's session in the memory of one pod and talks to the
browser over a WebSocket. With two replicas, the ALB could send a reconnect to
the other pod, which knows nothing about that session, and the page resets. To
scale it out: turn on ALB sticky sessions (`stickiness.enabled=true` in the
target group attributes annotation) so each browser stays on one pod, add a
PodDisruptionBudget, and accept that a pod restart still drops the sessions on
that pod. For this project, one replica is enough; all heavy work happens in
the queue workers, which scale independently.
