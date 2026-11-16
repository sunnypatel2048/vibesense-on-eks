# ADR-0008: Secrets in SSM Parameter Store, synced by External Secrets, never in Terraform

**Status:** Accepted

## Context

The app needs a YouTube API key, Gmail credentials, the RDS password and some Terraform outputs; Grafana needs an admin password.

## Decision

App secrets are SecureString parameters under `/vibesense/secrets/`, written by `scripts/put-secrets.sh` (`make secrets`), which also generates the Grafana password. Terraform publishes non-secret outputs under `/vibesense/platform/`. RDS manages its own master password in Secrets Manager. External Secrets Operator copies values into Kubernetes Secrets using its own Pod Identity role; the RDS secret's random name is found by pattern.

## Consequences

- Secrets never pass through Terraform: even with `ignore_changes`, refresh would write a managed parameter's value into state.
- Parameter Store's standard tier is free; Secrets Manager is used only where RDS requires it.
- Each pod receives only the secret variables it lists (the AI worker gets none).

## Alternatives considered

Secrets Manager for everything (per-secret monthly cost); Kubernetes Secrets in Git, even encrypted with SOPS or Sealed Secrets (key management becomes another problem); Terraform-managed parameters (values in state).
