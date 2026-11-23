# syntax=docker/dockerfile:1

# Pinned by digest (supply-chain reproducibility, ADR-0383 supply-chain gate):
# тег `3.14-slim-bookworm` плавает, сборка из разных недель давала разные
# базовые слои. Digest фиксирует точное содержимое; обновление базового
# образа = осознанный bump digest (см. docs/roadmap/PROD_READINESS_GAPS.md).
# Digest актуальлен на 2026-11-18.
FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    PIP_NO_CACHE_DIR=1 \
    PATH="/root/.local/bin:/app/.venv/bin:$PATH"

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

# Установка uv (официальный статичный бинарь, без pip).
# Pinned by version AND digest: `latest` плавал, версия uv определяет
# резолвинг uv.lock → невоспроизводимость сборки. Версия 0.11.7 совпадает
# с локальной/CI-версией. Digest актуален на 2026-11-18.
COPY --from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./

# Установка только runtime-зависимостей (без dev-группы) в /app/.venv.
# ADR-0381: кроме dev-light (aiosqlite/fastmcp) нужен extra sources-cdc —
# в нём psycopg3 (sync/async-драйвер PostgreSQL по умолчанию, ADR-0363).
# Без него образ стартует, но любой sync-движок БД падает на отсутствии
# драйвера, а контейнер с Oracle/MSSQL/MySQL — на том же.
#
# ADR-0442: набор extras задаётся build-ARG'ом. Extra ``workflow``
# (temporalio) обязателен в любом образе: без него **компилятор**
# workflow-деклараций падает («temporalio SDK not installed») → в контейнере
# регистрируется 0 workflow-деклараций, даже когда стенд использует
# LiteTemporalBackend. Поэтому extra входит в дефолт.
#   docker build --build-arg UV_EXTRAS="dev-light sources-cdc workflow" ...
# db_drivers ОБЯЗАТЕЛЕН для прод-образа: без него нет clickhouse-connect
# (транспорт аудита ClickHouse → «audit_silent_loss»: события аудита терялись
# безвозвратно) и нет бинарного psycopg для sync-движка БД.
ARG UV_EXTRAS="dev-light sources-cdc workflow db_drivers"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
        $(for extra in $UV_EXTRAS; do printf -- "--extra %s " "$extra"; done) && \
    # P1 (аудит 2026-11-18): `uv pip install ruamel-yaml` (без версии) тянул
    # СВЕЖУЮЮ версию из PyPI мимо uv.lock → невоспроизводимая сборка образа.
    # Причина хака: ruamel-yaml нужен в РАНТАЙМЕ (src/backend/dsl/workflow/
    # yaml_io.py импортирует его на уровне модуля, а модуль тянет
    # src/backend/dsl/workflow/__init__.py → src/backend/core/api/extensions.py),
    # но объявлен только в [dependency-groups] dev, а образ собирается с
    # `--no-dev`. Версия зафиксирована на версию из uv.lock (0.19.1),
    # у пакета нет зависимостей → --no-deps безопасен.
    # Каноническое лечение — перенести ruamel-yaml в [project].dependencies
    # и пересобрать uv.lock (требует согласования изменения lock-файла).
    uv pip install --no-deps "ruamel-yaml==0.19.1"

COPY src ./src
COPY manage.py ./manage.py
COPY alembic.ini ./
COPY config_profiles ./src/config_profiles
COPY extensions ./extensions

# Тот же digest, что и в builder-слое — иначе runtime-слои собирались бы
# из другого базового образа, чем слои зависимостей.
FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/src:/app" \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libpq5 \
        libssl3 \
        netcat-openbsd \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser && \
    mkdir -p /app /app/logs /app/.run && \
    chown -R appuser:appuser /app

COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv
COPY --from=builder --chown=appuser:appuser /app/src ./src
COPY --from=builder --chown=appuser:appuser /app/manage.py ./manage.py
COPY --from=builder --chown=appuser:appuser /app/alembic.ini ./alembic.ini
COPY --from=builder --chown=appuser:appuser /app/src/config_profiles ./src/config_profiles
COPY --from=builder --chown=appuser:appuser /app/extensions ./extensions

RUN chmod -R 750 /app && \
    find / -xdev -perm /6000 -type f -exec chmod a-s {} \; || true

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=3)" || exit 1

EXPOSE 8000 4200 50051

ENTRYPOINT ["/usr/bin/tini", "--", "python", "manage.py"]
CMD ["run"]
