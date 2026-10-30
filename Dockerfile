# syntax=docker/dockerfile:1
#
# Two images from one file:
#   --target app  UI, ingestion, aggregation, notification (pick one with the command)
#   --target ai   the sentiment worker, with its model baked in
#
# Build for the Graviton nodes (and natively on Apple Silicon):
#   docker buildx build --platform linux/arm64 --target app -t vibesense-app:dev --load .
#   docker buildx build --platform linux/arm64 --target ai  -t vibesense-ai:dev  --load .

ARG PYTHON_VERSION=3.12
# Multi-platform digest of python:3.12-slim. Pinned so builds are reproducible;
# bump it deliberately (rebuild, rescan, rerun the golden check).
ARG PYTHON_DIGEST=sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
# The exact Hugging Face commit the golden results (tests/fixtures/) were recorded with.
ARG MODEL_NAME=tabularisai/multilingual-sentiment-analysis
ARG MODEL_REVISION=eea032081f8d247b4303ef3565e7cec1b6f201c9
# Same uv as `make lock` uses locally (`uv --version`).
ARG UV_VERSION=0.13.6

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------
# Shared base: interpreter settings only.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim@${PYTHON_DIGEST} AS python-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# ---------------------------------------------------------------------------
# Builder: compilers live here and never reach a runtime image.
# ---------------------------------------------------------------------------
FROM python-base AS builder
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    VIRTUAL_ENV=/opt/venv \
    UV_NO_CACHE=1 \
    UV_INDEX_STRATEGY=unsafe-best-match

FROM builder AS app-deps
COPY requirements/app.txt /tmp/requirements.txt
# uv, not pip, so installs follow the same index rules as `make lock`. The lock
# pins torch to its `+cpu` build, which only PyTorch's CPU index has.
# --no-deps: install exactly the lock file, never resolve anything extra.
RUN uv pip install --no-deps -r /tmp/requirements.txt

FROM builder AS ai-deps
COPY requirements/ai.txt /tmp/requirements.txt
RUN uv pip install --no-deps -r /tmp/requirements.txt

# Download the model at build time, so pods start without network access to
# Hugging Face and scale-from-zero (KEDA) doesn't wait on a download.
FROM ai-deps AS ai-model
ENV HF_HOME=/models
ARG MODEL_NAME
ARG MODEL_REVISION
RUN python -c "from transformers import pipeline; pipeline('sentiment-analysis', model='${MODEL_NAME}', revision='${MODEL_REVISION}')"

# ---------------------------------------------------------------------------
# Runtime base: no compilers, a non-root user, the app code's home.
# ---------------------------------------------------------------------------
FROM python-base AS runtime
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app
WORKDIR /app
ENV PATH=/opt/venv/bin:$PATH

# ---------------------------------------------------------------------------
# app image
# ---------------------------------------------------------------------------
FROM runtime AS app
COPY --from=app-deps /opt/venv /opt/venv
# The startup schema check (src/common/db.py) reads these at runtime.
COPY alembic.ini ./
COPY alembic ./alembic
COPY .streamlit ./.streamlit
COPY src ./src
USER 10001
# 8501: Streamlit UI. 9000: worker /healthz, /readyz, /metrics.
EXPOSE 8501 9000
# Each Deployment sets its own command, e.g. `python -m src.ingestion_service.app`.
CMD ["python", "-c", "print('Choose a service, e.g. python -m src.ingestion_service.app')"]

# ---------------------------------------------------------------------------
# ai image
# ---------------------------------------------------------------------------
FROM runtime AS ai
ARG MODEL_REVISION
COPY --from=ai-deps /opt/venv /opt/venv
COPY --from=ai-model --chown=10001:10001 /models /models
ENV HF_HOME=/models \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    MODEL_REVISION=${MODEL_REVISION}
COPY src ./src
USER 10001
EXPOSE 9000
CMD ["python", "-m", "src.ai_service.app"]
