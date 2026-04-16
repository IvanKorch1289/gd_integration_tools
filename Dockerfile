# syntax=docker/dockerfile:1

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
        netcat-openbsd \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock* ./

RUN poetry install --only main --no-root --no-ansi && \
    poetry cache clear pypi --all

COPY app ./app
COPY alembic.ini ./
COPY config.yml ./
COPY .env ./
COPY scripts/manage.sh ./scripts/manage.sh

RUN chmod +x ./scripts/manage.sh

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
        netcat-openbsd \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser && \
    mkdir -p /app /app/logs /app/.run && \
    chown -R appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /app/app ./app
COPY --from=builder --chown=appuser:appuser /app/alembic.ini ./alembic.ini
COPY --from=builder --chown=appuser:appuser /app/config.yml ./config.yml
COPY --from=builder --chown=appuser:appuser /app/.env ./.env
COPY --from=builder --chown=appuser:appuser /app/scripts/manage.sh ./scripts/manage.sh

RUN chmod 755 ./scripts/manage.sh && \
    chmod -R 750 /app && \
    find / -xdev -perm /6000 -type f -exec chmod a-s {} \; || true

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=3)" || exit 1

EXPOSE 8000 4200 50051

ENTRYPOINT ["/usr/bin/tini", "--", "/bin/sh", "./scripts/manage.sh"]
CMD ["run"]
