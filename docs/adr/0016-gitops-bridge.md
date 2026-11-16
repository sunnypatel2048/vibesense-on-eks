# ADR-0016: GitOps Bridge: Terraform outputs reach Argo CD through the cluster record

**Status:** Accepted

## Context

The chart needs values that must not be in a public repository: the ECR registry and SQS URLs (both contain the AWS account ID) and the CIDRs allowed to reach the UI (the admin's IP).

## Decision

`scripts/bootstrap-argocd.sh` reads Terraform's `gitops_metadata` output and registers the cluster with Argo CD as a cluster Secret annotated with those values. `deploy/apps/vibesense.yaml` is an ApplicationSet whose cluster generator copies the annotations into the chart's values (`valuesObject`, not `--set`, which would split on the commas in a CIDR list).

## Consequences

- The account ID and IP exist only in Terraform state and in the cluster, never in Git.
- Labelling a second cluster `vibesense.io/workloads=true` would deploy the app there too.
- The chart refuses to render without the values, so a missing annotation fails loudly.

## Alternatives considered

Values committed to Git (leaks the account ID); Argo CD Image Updater for the registry (solves only part of it); a values file kept outside Git (breaks GitOps).
