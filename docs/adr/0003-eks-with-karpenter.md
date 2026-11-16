# ADR-0003: EKS with a small managed node group, plus Karpenter for burst capacity

**Status:** Accepted

## Context

The platform has to show Kubernetes operations (scheduling, autoscaling, GitOps), cost little, and come up and go down with one command.

## Decision

EKS (Kubernetes 1.37, `upgrade_policy = STANDARD` so an ageing version is upgraded rather than billed for extended support), API-mode access entries, and a managed node group `system` of 2 Spot Graviton nodes (`t4g`/`m6g`/`m7g.large`) labelled `vibesense/node-role=system`. Platform components and the light workers run there. Karpenter launches extra nodes from a tainted `burst` NodePool for the AI worker only (ADR-0010).

## Consequences

- Kubernetes is the skill these roles ask for; EKS is the managed way to run it on AWS.
- The control plane costs $0.10/hour, so the cluster is destroyed after every session (`make down`).
- The node group gives Karpenter's own controller somewhere stable to run.

## Alternatives considered

ECS on Fargate (simpler and cheaper to operate, but hides the scheduling and autoscaling this project exists to show); EKS Auto Mode (adds a per-instance management fee and manages Karpenter itself); self-managed Kubernetes (the control plane becomes something to operate).
