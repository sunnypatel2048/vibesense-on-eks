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

# ---------------------------------------------------------------------------
# Shared base: interpreter settings only.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS python-base
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
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

FROM builder AS app-deps
COPY requirements/app.txt /tmp/requirements.txt
# --no-deps: install exactly the lock file, never resolve anything extra.
RUN pip install --no-deps -r /tmp/requirements.txt

FROM builder AS ai-deps
COPY requirements/ai.txt /tmp/requirements.txt
RUN pip install --no-deps -r /tmp/requirements.txt

# Download the model at build time, so pods start without network access to
# Hugging Face and scale-from-zero (KEDA) doesn't wait on a download.
FROM ai-deps AS ai-model
ENV HF_HOME=/models
ARG MODEL_NAME=tabularisai/multilingual-sentiment-analysis
RUN python -c "from transformers import pipeline; pipeline('sentiment-analysis', model='${MODEL_NAME}')"

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
COPY --from=ai-deps /opt/venv /opt/venv
COPY --from=ai-model --chown=10001:10001 /models /models
ENV HF_HOME=/models \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
COPY src ./src
USER 10001
EXPOSE 9000
CMD ["python", "-m", "src.ai_service.app"]
