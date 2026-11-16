# ADR-0009: EKS Pod Identity with one IAM role per workload

**Status:** Accepted

## Context

Pods call SQS, EventBridge Scheduler, SSM, SNS and CloudWatch Logs. Static keys are out of the question; the node's role would give every pod the union of all permissions.

## Decision

Each workload has its own role (`infra/modules/workload-role`), bound to its service account by an EKS Pod Identity association. Trust policies include `aws:SourceAccount` and the cluster ARN. Policies are scoped to exact resources, for example the AI worker may receive from the analysis queue and send to the aggregation queue, nothing else. IRSA is switched off (`enable_irsa = false`), and Karpenter's nodes block pods from the instance metadata service (hop limit 1).

## Consequences

- A compromised pod reaches only its own queues; verified live (the AI role can't see the notification queue, and SSM is denied).
- No per-cluster OIDC provider to create and clean up.
- Service account names are a contract between Terraform and the Helm chart.

## Alternatives considered

IRSA (works, but needs an OIDC provider per cluster and role ARNs annotated on service accounts, which would put the account ID in Git); the node instance role (no isolation).
