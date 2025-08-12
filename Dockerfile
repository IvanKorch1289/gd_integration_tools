# Этап сборки с минимальным базовым образом
FROM python:3.12-slim-bookworm AS builder

# Устанавливаем переменные среды
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PATH="/opt/poetry/bin:$PATH"

WORKDIR /app

# Устанавливаем только необходимые зависимости для сборки
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    zlib1g-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Poetry
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# Копируем зависимости
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости без dev-зависимостей
RUN poetry install --only main --no-root --no-ansi && \
    poetry cache clear pypi --all

# Этап рантайма с ultra-slim образом
FROM python:3.12-alpine3.19

# Устанавливаем переменные среды
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app" \
    PATH="/app/.venv/bin:$PATH"

# Устанавливаем runtime-зависимости (минимальный набор)
RUN apk add --no-cache \
    libpq \
    jpeg \
    # Добавляем libstdc++ только если он действительно нужен
    libstdc++

# Создаем непривилегированного пользователя
RUN adduser -D appuser && \
    mkdir -p /app && \
    chown appuser:appuser /app

WORKDIR /app

# Копируем виртуальное окружение из builder
COPY --from=builder --chown=appuser:appuser /app/.venv ./.venv

# Копируем файлы приложения
COPY --chown=appuser:appuser --chmod=755 entrypoint.sh start.sh ./
COPY --chown=appuser:appuser --chmod=644 config.yml .env alembic.ini ./
COPY --chown=appuser:appuser --chmod=755 ./app ./app

# Устанавливаем ограничения безопасности
RUN find / -xdev -perm +6000 -type f -exec chmod a-s {} \; || true && \
    chmod -R 750 /app && \
    chown -R appuser:appuser /app

# Переключаемся на непривилегированного пользователя
USER appuser

# Настройка healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('localhost', 8000), timeout=5)" || exit 1

EXPOSE 8000 4200 50051

# Запускаем приложение
CMD ["/bin/sh", "./entrypoint.sh"]