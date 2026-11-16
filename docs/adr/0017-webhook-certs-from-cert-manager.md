# ADR-0017: Admission webhook certificates from cert-manager, not from chart rendering

**Status:** Accepted

## Context

The AWS Load Balancer Controller's chart generates a new CA and webhook certificate every time it's rendered. Argo CD renders charts repeatedly, so the webhook's CA and the controller's certificate drifted apart and every Ingress was rejected (`x509: certificate signed by unknown authority`). Ignoring those fields fixed a running cluster but not a fresh install.

## Decision

cert-manager (wave 0) issues the controller's webhook certificate at runtime (`enableCertManager: true`), and its CA injector writes the matching CA into the webhook configurations; Argo CD ignores just that field. kube-prometheus-stack's operator webhook uses cert-manager the same way. Other add-ons (External Secrets, KEDA) already rotate their own certificates at runtime and get the same ignore rule up front.

## Consequences

- Nothing certificate-related comes out of a chart render, so nothing can drift from Git.
- One more controller (three small pods) and a wave dependency for the load balancer controller.

## Alternatives considered

Ignoring the fields (fails on fresh installs); disabling the webhooks (loses validation); certificates committed to Git (private keys in a repository).
