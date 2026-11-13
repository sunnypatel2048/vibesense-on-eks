# Security

## Container image vulnerability policy

Both images are scanned with [Trivy](https://trivy.dev) for HIGH and CRITICAL
vulnerabilities in OS packages and Python packages.

| Finding | Action |
| --- | --- |
| Python package, fix available | Upgrade (raise the floor in `requirements/*.in`, `make lock`, rebuild). |
| OS package, fix available | Bump the pinned base image digest in the `Dockerfile`, rebuild. |
| No fix available | Accept, with a reason and a review date, in this file. |

The CI gate (Phase 7) runs Trivy with `--ignore-unfixed --severity HIGH,CRITICAL`
and fails the build on any finding that **has** a fix. When an accepted finding
gets a fix upstream, the gate starts failing and forces the upgrade.

ML dependency upgrades (torch, transformers, the model revision) must also pass
`scripts/sentiment_golden.py --check`: every label on the 20 reference comments
matches and every score is within 0.02 of `tests/fixtures/sentiment_golden.json`.

## Baseline scan: 2026-10-29

Base image: `python:3.12-slim` (Debian 13.7), before pinning.

| Image | OS packages | Python packages |
| --- | --- | --- |
| `app` | 44 HIGH, none fixable | 40 in Pillow 11.3.0 (incl. CRITICAL), fixed in 13.0.0 |
| `ai` | 44 HIGH, none fixable | torch 2.2.0 (1 CRITICAL, fixed in 2.6.0); transformers 4.35.2 (1 CRITICAL, 7 HIGH, fixed by 5.10.0) |

### Fixed

| Package | From | To | Notes |
| --- | --- | --- | --- |
| pillow (app, via Streamlit) | 11.3.0 | ≥ 13.0.0 | Not reachable (the app never decodes images) but fixable, so upgraded. Streamlit raised to the newest release allowing it. |
| torch (ai) | 2.2.0 | ≥ 2.6.0 | CVE-2025-32434: code execution via `torch.load` on untrusted files. |
| transformers (ai) | 4.35.2 | ≥ 5.10.0 | Deserialization and code-execution advisories (CVE-2023-6730, CVE-2023-7018, CVE-2024-11392/3/4, CVE-2026-4372, CVE-2026-5241, CVE-2026-9856). Major version upgrade; verified with the golden check. |

Also pinned: the base image by digest, and the model by Hugging Face revision
(`eea032081f8d247b4303ef3565e7cec1b6f201c9`), so a rebuild can't silently change either.

### Accepted: Debian packages with no fix available

Present in both images. Status "affected" in Debian 13 with no fixed version at
scan time. **Review by 2027-01-31**, or sooner if the CI gate reports a fix.

| Source | CVEs | Why accepted |
| --- | --- | --- |
| util-linux (`mount`, `login`, `libmount1`, `libblkid1`, …) | CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 | Local privilege escalation through mount helpers, `nsenter` and bind mounts. The containers run as non-root UID 10001 and never invoke these tools; pods drop all capabilities and disallow privilege escalation (Phase 6). |
| acl (`libacl1`) | CVE-2026-54369 | Symlink traversal by a privileged caller of libacl. Nothing in the images calls it as root. |
| ncurses (`libtinfo6`, `libncursesw6`, …) | CVE-2025-69720 | Buffer overflow on crafted terminal data. The services never render untrusted input to a terminal. |
| systemd (`libsystemd0`, `libudev1`) | CVE-2026-16742 | Privilege escalation in `systemd-homed`, which isn't running in a container. |
| perl (`perl-base`) | CVE-2026-9538 | Denial of service in Archive::Tar on crafted archives. The services never run Perl. Debian status: fix deferred. |

**Alternative considered:** a distroless or Chainguard base image would remove
nearly all OS packages, and these findings with them. Trade-offs: no shell for
debugging, and the Python version must match what the base provides. Worth
revisiting if OS findings become a recurring cost.

## CI access to AWS

GitHub Actions uses OIDC: each run exchanges a GitHub-signed token for AWS
credentials that expire after one hour. No access keys are stored in GitHub.

| Role | Trusted `sub` (exact match) | Permissions |
| --- | --- | --- |
| `vibesense-ci-push` | `repo:sunnypatel2048/vibesense-on-eks:ref:refs/heads/main` | Push to the two ECR repositories |
| `vibesense-ci-plan` | `...:pull_request` and `...:ref:refs/heads/main` | `ReadOnlyAccess`, plus writing/deleting `*.tflock` in the state bucket |

- Both trust policies check `aud` and `sub` with `StringEquals`. Checking only the
  audience would let any GitHub repository assume the roles.
- There is no apply role. The platform layer is applied from a laptop, so CI can
  never create cost or destroy resources.
- Pull requests from forks receive no OIDC token. Workflows must never use
  `pull_request_target`, which runs fork code with the base repository's permissions.
- `ReadOnlyAccess` is broad, because a hand-written read policy would break
  whenever Terraform manages a new resource type. Its one dangerous read, the
  app's secrets, is removed with an explicit deny (next section).

## Terraform policy scan (Checkov)

`make lint-infra` runs `terraform fmt`, tflint and Checkov over `infra/`; CI runs
the same on infrastructure PRs. Accepted findings are skipped **inline, on the
resource, with a reason**, never globally, so each one is visible in review.

Baseline, 2026-11-12, bootstrap layer: 92 passed, 7 skipped, 0 failed.

Checkov scans this repository's own code. Third-party modules (for example
`terraform-aws-modules/vpc`) are pinned to exact versions and their resources are
reviewed in `terraform plan`; their internals aren't scanned, since most findings
there concern resources the module only creates when switched on.

| Check | Resource | Why skipped | Production would |
| --- | --- | --- | --- |
| CKV_AWS_26 (SNS KMS encryption) | `aws_sns_topic.alerts` | CloudWatch alarms can't publish to a topic encrypted with the AWS-managed `aws/sns` key; alarm messages aren't sensitive. | Customer-managed KMS key whose key policy allows CloudWatch. |
| CKV_AWS_136 (ECR KMS encryption) | `aws_ecr_repository.image` (both) | Already encrypted at rest with AES-256; images contain code, not secrets. | Customer-managed KMS key. ECR encryption is fixed at creation, so switching means recreating the repositories. |
| CKV_AWS_145 (S3 KMS encryption) | `aws_s3_bucket.tfstate` | SSE-S3 at no cost. | Customer-managed KMS key: every state read is logged as a decrypt, and access can be revoked at the key. |
| CKV_AWS_18 (S3 access logging) | `aws_s3_bucket.tfstate` | Needs a second log bucket for a single-user account; CloudTrail already records bucket configuration changes. | Server access logs or CloudTrail S3 data events, recording every state read. |
| CKV_AWS_144 (S3 cross-region replication) | `aws_s3_bucket.tfstate` | Versioning covers corruption and deletion; the whole project is single-region. | Replicate state to a second region as part of multi-region recovery. |
| CKV2_AWS_62 (S3 event notifications) | `aws_s3_bucket.tfstate` | Nothing needs to react to state writes. | Optional: alert on unexpected state changes. |
| CKV_AWS_293 (RDS deletion protection) | `aws_db_instance.main` | `terraform destroy` would fail on every `make down`. | Enable it: deleting a production database should take two deliberate steps. |
| CKV_AWS_157 (RDS Multi-AZ) | `aws_db_instance.main` | Doubles the cost for failover a demo doesn't need. | Multi-AZ or Aurora for automatic failover. |
| CKV_AWS_161 (RDS IAM authentication) | `aws_db_instance.main` | The password is generated by RDS and kept in Secrets Manager, never handled by a person or Terraform. IAM auth needs a fresh 15-minute token per connection in the app. | IAM auth via each pod's IAM role, removing the password. |
| CKV_AWS_129 (RDS log exports) | `aws_db_instance.main` | Billed per GB, and RDS-created log groups outlive the instance, piling up across `make up`/`make down`. | Export PostgreSQL logs with a retention period. |
| CKV2_AWS_30 (PostgreSQL query logging) | `aws_db_instance.main` | Needs log exports plus a custom parameter group, and logged statements would contain users' email addresses. | Log slow queries and errors, not every statement. |
| CKV_AWS_118 (RDS enhanced monitoring) | `aws_db_instance.main` | Needs an extra IAM role; OS metrics bill through CloudWatch Logs. | Enable for OS-level metrics. |
| CKV_AWS_353 (RDS Performance Insights) | `aws_db_instance.main` | Demo-scale database; application metrics go to Grafana (Phase 9). | CloudWatch Database Insights. |
| CKV2_AWS_34 (SSM parameter encryption) | `aws_ssm_parameter.platform_config` | Identifiers (ARNs, a hostname, a port), not secrets; plain text keeps them readable when debugging. Secrets are SecureString under `/vibesense/secrets/`. | Same split; SecureString only for actual secrets. |
| CKV_TF_1 (module source pinned to a commit hash) | `module.vpc` (platform) | Exact registry version pinned (`6.7.3`); upgrades are reviewed PRs. A Git commit source would lose readable versions and automated update PRs. | Commit-hash Git sources, updated by an automated dependency bot. |

## Secrets

The YouTube API key and Gmail credentials are `SecureString` parameters under
`/vibesense/secrets/`, written by `make secrets` (`scripts/put-secrets.sh`), and
deliberately **not managed by Terraform**.

Why not Terraform with a placeholder and `ignore_changes = [value]`: that only
suppresses planned changes. Every `plan` still refreshes the resource, reading
the decrypted value from AWS and writing it into the state file, so the real
secret would end up in plain text in the state bucket.

- The script reads values with hidden prompts and passes them on stdin, so they
  don't appear in shell history or the process list.
- `vibesense-ci-plan` has an explicit deny on reading `/vibesense/secrets/*` and
  on by-path reads. Terraform never reads these parameters, so no plan breaks.
- Non-secret configuration that Terraform creates (Phase 4) lives under
  `/vibesense/platform/`, outside the denied path.
- In the cluster, only the External Secrets Operator's role may read
  `/vibesense/secrets/*` (Task 4.7).

## Package indexes

The `ai` image installs torch from PyTorch's CPU-only index
(`download.pytorch.org/whl/cpu`); PyPI's Linux torch is a CUDA build that adds
about 8 GB of NVIDIA libraries the Graviton nodes can't use. That index also
mirrors old copies of common packages, and the first lock taken from it pinned
stale urllib3 1.26.13, setuptools 78.1.0 and httpx2 2.3.0 (12 HIGH findings).

So the locks use uv's `unsafe-best-match` index strategy (best version across
both indexes) and pin torch to the exact `+cpu` build, which exists only on the
PyTorch index. The usual risk of multiple indexes is dependency confusion: an
attacker publishing a same-named package on one of them. Both indexes here are
first-party and torch is pinned exactly, so the risk is accepted.

## How to rescan

```bash
docker buildx build --platform linux/arm64 --target app -t vibesense-app:dev --load .
docker buildx build --platform linux/arm64 --target ai  -t vibesense-ai:dev  --load .
trivy image --ignore-unfixed --severity HIGH,CRITICAL vibesense-app:dev
trivy image --ignore-unfixed --severity HIGH,CRITICAL vibesense-ai:dev
```
