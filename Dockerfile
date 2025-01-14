FROM python:3.12-alpine AS base

ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.3.2 \
    POETRY_HOME="/opt/poetry" \
    PATH="/opt/poetry/bin:$PATH"

WORKDIR /app

RUN apk add --update --no-cache gcc musl-dev libffi-dev openssl-dev cargo make
RUN pip install poetry
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false && \
    poetry install --no-root

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]