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
