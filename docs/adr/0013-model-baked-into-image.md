# ADR-0013: The model is baked into the image, with a golden output check

**Status:** Accepted

## Context

The AI worker uses `tabularisai/multilingual-sentiment-analysis` from Hugging Face. Downloading it at startup would slow scale-from-zero and make pods depend on Hugging Face being up.

## Decision

The `ai` image downloads the model at build time, pinned to an exact Hugging Face revision, and runs offline (`HF_HUB_OFFLINE=1`). PyTorch is the CPU-only build. `scripts/sentiment_golden.py --check` scores 20 reference comments with no network and fails if any label changes or any score moves more than 0.02; CI runs it on every pull request.

## Consequences

- Deterministic startup; a pod needs only ECR.
- A 2.4 GB image (about 790 MB compressed), which dominates cold start on a new node.
- Upgrading torch, transformers or the model revision is safe only if the golden check passes.

## Alternatives considered

Download at startup (slower, fragile); a SageMaker endpoint (standing cost, and a different track); GPU instances (unnecessary for this model and volume).
