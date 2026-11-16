# ADR-0019: CI with OIDC, no apply role, and pinned actions

**Status:** Accepted

## Context

CI builds images and checks infrastructure for a public repository. Long-lived AWS keys in GitHub, or a CI role that can apply Terraform, would make the repository a path into the account.

## Decision

GitHub Actions authenticates to AWS with OIDC. Trust policies match the exact `sub`, including the owner's and repository's numeric IDs, so a re-registered look-alike repository can't match. `vibesense-ci-push` (main only) pushes to ECR; `vibesense-ci-plan` (pull requests and main) is read-only plus the state lock, with an explicit deny on app secrets. There is no apply role. Releases bump the image tag in Git with a deploy key held as a secret of a `release` environment that only `main` may use; Argo CD does the deploying. Every action is pinned to a commit SHA, kept current by Dependabot. A repository ruleset requires pull requests and the `ci passed` and `infra passed` checks.

## Consequences

- CI can never create cost or destroy resources; the worst a compromised workflow can do is push an image or read non-secret configuration.
- Measured: merge to new pods Ready in 261 s with no `kubectl`.
- The deploy key is the one long-lived credential in CI; a GitHub App would remove it at the cost of more setup.

## Alternatives considered

Access keys in GitHub secrets; a CI apply role; push-based deploys with `kubectl` or Helm from CI; tag-pinned actions (tags can be moved, as in the 2025 `tj-actions/changed-files` compromise).
