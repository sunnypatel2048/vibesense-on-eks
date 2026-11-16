# ADR-0006: Terraform in two layers with separate state

**Status:** Accepted

## Context

Some resources must survive every teardown (the state bucket, ECR images, CI roles, budgets, the alert topic); the rest should be destroyed after every session.

## Decision

`infra/bootstrap` (persistent) and `infra/platform` (ephemeral) share one S3 state bucket under different keys, with native S3 locking (`use_lockfile`, no DynamoDB). The platform layer looks bootstrap resources up by name rather than reading its state. Community modules (`terraform-aws-modules` vpc 6.7.3, eks 21.29.0) are pinned to exact versions. The account ID never enters Git: the bucket name lives in a gitignored `backend.hcl`.

## Consequences

- `make down` can never delete images, state or CI access: they're in another state file.
- A smaller blast radius per `apply`.
- Bootstrapping the state bucket needs one manual state migration (documented in `infra/bootstrap/README.md`).

## Alternatives considered

One state file (teardown would have to target around persistent resources); AWS CDK (fine, but Terraform is more widely asked for); hand-written resources instead of modules (more code to own).
