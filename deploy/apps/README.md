# deploy/apps

One Argo CD `Application` (or `ApplicationSet`) per file. The root app (`deploy/root-app.yaml`)
installs everything here that's on `main`.

## Sync waves

Waves install in order; each waits for the previous one to be healthy (this
relies on the Application health check in `deploy/platform/argocd-values.yaml`).

| Wave | Applications | Why this order |
| --- | --- | --- |
| -1 | repositories (`repositories.yaml`) | Tells Argo CD where OCI charts live, before any app needs them |
| 0 | metrics-server, cert-manager, external-secrets, keda | Controllers and CRDs everything else depends on |
| 1 | aws-load-balancer-controller, karpenter | Need cert-manager's CRDs (load balancer controller); Karpenter after the core controllers |
| 2 | cluster-config (`deploy/cluster-config/`), monitoring (kube-prometheus-stack + `deploy/monitoring/`) | Objects whose types waves 0–1 install: ClusterSecretStores, NodePool, EC2NodeClass, cert-manager Certificates |
| 3 | vibesense (an ApplicationSet) | Uses ExternalSecrets, an Ingress (ALB), KEDA ScaledObjects and PodMonitors |

## Pattern

Each add-on has two sources: the upstream Helm chart pinned to an exact
version, and this repo for its values file under `deploy/platform/`. Each has
the cascade-delete finalizer, so deleting the Application removes what it
installed.
