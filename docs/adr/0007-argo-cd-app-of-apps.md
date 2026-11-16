# ADR-0007: Argo CD app-of-apps for everything inside the cluster

**Status:** Accepted

## Context

Something has to install about a dozen add-ons and the app, in order, and keep them as declared.

## Decision

Terraform stops at the cluster. `scripts/bootstrap-argocd.sh` installs Argo CD with Helm and applies one root Application, which syncs every Application in `deploy/apps/` from `main`, ordered by sync waves (−1 CRDs and repositories; 0 controllers; 1 load balancer controller and Karpenter; 2 cluster config and monitoring; 3 the app). A custom health check makes each wave wait for the previous one. Add-ons are upstream Helm charts pinned exactly, with values from this repository.

## Consequences

- No Terraform Helm/Kubernetes providers, and none of their chicken-and-egg problems with a cluster that doesn't exist yet.
- Cluster state lives in Git; self-heal reverts manual changes. CI never holds cluster credentials (ADR-0019).
- Teardown must stop self-heal first, or Argo CD recreates what's being deleted (`scripts/down.sh` step 1).

## Alternatives considered

Terraform's Helm provider for everything; Flux (equally valid, Argo CD's UI helps in demos); the EKS managed Argo CD capability (billed separately).
