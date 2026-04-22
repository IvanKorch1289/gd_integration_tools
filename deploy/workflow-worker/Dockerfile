# syntax=docker/dockerfile:1
# Durable workflow worker — standalone образ (IL-WF1.4).
# Тот же base + poetry stack, что и основной Dockerfile. ENTRYPOINT
# отличается: вместо FastAPI-процесса крутим `src.workflows.worker run`.

FROM python:3.14-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/poetry/bin:$PATH"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        gcc \
        libffi-dev \
        libpq-dev \
        libssl-dev \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock* ./

RUN poetry install --only main --no-root --no-ansi && \
    poetry cache clear pypi --all

COPY src ./app
COPY alembic.ini ./
COPY config.yml ./


FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app" \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        libpq5 \
        libssl3 \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser && \
    mkdir -p /app /app/logs && \
    chown -R appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /app/app ./app
COPY --from=builder --chown=appuser:appuser /app/alembic.ini ./alembic.ini
COPY --from=builder --chown=appuser:appuser /app/config.yml ./config.yml

USER appuser

# K8s probes HTTP port (см. src/workflows/worker_probes.py).
EXPOSE 9100

# Liveness: TCP connect на probes port достаточно (HTTP-200 даёт /healthz).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 9100), timeout=3)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "app.workflows.worker"]
CMD ["run"]
