# deploy/apps

One Argo CD `Application` per file. The root app (`deploy/root-app.yaml`)
installs everything here that's on `main`.

## Sync waves

Waves install in order; each waits for the previous one to be healthy (this
relies on the Application health check in `deploy/platform/argocd-values.yaml`).

| Wave | Applications | Why this order |
| --- | --- | --- |
| 0 | metrics-server, aws-load-balancer-controller, external-secrets, keda | Controllers and CRDs everything else depends on |
| 1 | karpenter | Needs the cluster's core controllers in place |
| 2 | kube-prometheus-stack | Monitoring CRDs (ServiceMonitor, PodMonitor) |
| 3 | vibesense | Uses ExternalSecrets, an Ingress (ALB), KEDA ScaledObjects and PodMonitors |

## Pattern

Each add-on has two sources: the upstream Helm chart pinned to an exact
version, and this repo for its values file under `deploy/platform/`. Each has
the cascade-delete finalizer, so deleting the Application removes what it
installed.
