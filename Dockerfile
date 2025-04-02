FROM python:3.12-alpine AS base

ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.7.0 \
    POETRY_HOME="/opt/poetry" \
    PATH="/opt/poetry/bin:$PATH"

WORKDIR /app

# Устанавливаем системные зависимости
RUN apk add --update --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    make \
    postgresql-dev \
    python3-dev \
    libpq-dev \
    libc6-compat \
    zlib-dev \
    jpeg-dev \
    build-base

# Устанавливаем Poetry
RUN pip install "poetry==$POETRY_VERSION"

# Копируем зависимости
COPY pyproject.toml poetry.lock* alembic.ini ./

# Устанавливаем python зависимости
RUN poetry config installer.allow-yanked true && \
    poetry install ... && \
    poetry config installer.allow-yanked false

# Копируем исходный код
COPY ./app ./app
COPY config.yml .env alembic.ini entrypoint.sh start.sh ./

# Настройки прав и здоровья
RUN chmod +x start.sh
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD nc -z localhost 8000 || exit 1

# Порт для приложения
EXPOSE 8000 4200 50051

# Запуск скрипта
CMD ["./entrypoint.sh"]
