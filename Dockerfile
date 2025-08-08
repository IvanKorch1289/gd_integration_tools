# Этап сборки с использованием Debian
FROM python:3.12-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    PATH="/opt/poetry/bin:$PATH"

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    zlib1g-dev \
    libjpeg-dev \
    cargo \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Poetry
RUN pip install "poetry==$POETRY_VERSION"

# Копируем зависимости
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости
RUN poetry config virtualenvs.in-project true && \
    poetry install --only=main --no-interaction --no-ansi --no-root && \
    poetry cache clear pypi --all

# Этап рантайма
FROM python:3.12-slim

# Устанавливаем переменные среды перед WORKDIR
ENV PYTHONPATH="/app" \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Рантайм-зависимости
RUN apt-get update && apt-get install -y \
    libpq5 \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

# Копируем виртуальное окружение
COPY --from=builder /app/.venv ./.venv

# Копируем исходный код
COPY --chmod=755 entrypoint.sh start.sh ./
COPY --chmod=644 config.yml .env alembic.ini ./
COPY --chmod=644 ./app ./app

HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD nc -z localhost 8000 || exit 1

EXPOSE 8000 4200 50051

CMD ["/bin/bash", "./entrypoint.sh"]
