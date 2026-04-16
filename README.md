# GD Integration Tools

API-шлюз для интеграции с внешними сервисами и внутренними workflow.

[![Python](https://img.shields.io/badge/Python-3.14+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-blue?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-blue?logo=postgresql&logoColor=white)](https://postgresql.org)
[![RabbitMQ](https://img.shields.io/badge/RabbitMQ-orange?logo=rabbitmq&logoColor=white)](https://rabbitmq.com)
[![Docker](https://img.shields.io/badge/Docker-blue?logo=docker&logoColor=white)](https://docker.com)

## Возможности

- Асинхронное API на FastAPI
- Асинхронный доступ к PostgreSQL
- Интеграция с RabbitMQ
- Workflow и orchestration через Prefect
- Применение миграций через Alembic
- Централизованное управление запуском через `scripts/manage.sh`
- Локальный dev-flow через `Makefile`
- Запуск в Docker-контейнере
- Базовые security и quality проверки

## Стек

- Python 3.14
- FastAPI
- SQLAlchemy / Alembic
- PostgreSQL
- RabbitMQ
- Prefect
- Docker
- Poetry

## Структура управления проектом

Проект больше не использует `start.sh`, `stop.sh` и `init-rabbitmq.sh` как отдельные точки входа.

Теперь управление вынесено в:

- `scripts/manage.sh` — единая точка управления сервисами
- `Makefile` — удобные команды для локальной разработки
- `Dockerfile` — контейнерный запуск через `scripts/manage.sh`

## Требования

- Python 3.14
- Poetry
- Docker и Docker Compose, если нужен контейнерный запуск
- Доступные внешние сервисы: PostgreSQL, RabbitMQ и другие зависимости проекта

## Установка

### 1. Установить Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

### 2. Установить зависимости

```bash
make init
```

или

```bash
poetry config virtualenvs.in-project true
poetry install --with dev
```

### 3. Настроить переменные окружения

Создай `.env` и задай в нём нужные переменные проекта.

Пример:

```env
SEC_JWT_SECRET=
SEC_SECRET_KEY=
SEC_API_KEY=

DB_USERNAME=
DB_PASSWORD=
DB_NAME=

SKB_API_KEY=
DADATA_API_KEY=

FS_ACCESS_KEY=
FS_SECRET_KEY=

LOG_INTERFACE_URL=
LOG_PASSWORD_SECRET=
LOG_ROOT_PASSWORD_SHA2=

REDIS_PASSWORD=

MAIL_USERNAME=
MAIL_PASSWORD=

GF_USER=
GF_PASSWORD=

OUTLINE_SECRET_KEY=
OUTLINE_UTILS_SECRET=
OUTLINE_URL=
OUTLINE_COLLABORATION_URL=

QUEUE_USERNAME=
QUEUE_PASSWORD=

VAULT_ADDR=
VAULT_TOKEN=
VAULT_SECRET_PATH=

MONGO_USERNAME=
MONGO_PASSWORD=

SONAR_TOKEN=
```

## Локальный запуск

### Применить миграции

```bash
make migrate
```

### Запустить проект в фоне

```bash
make run
```

### Запустить проект в foreground-режиме

```bash
make run-fg
```

### Остановить проект

```bash
make stop
```

### Проверить статус сервисов

```bash
make status
```

## Основные команды Makefile

### Качество кода

```bash
make format
make lint
make code-lint
make code-check
make code-clean
```

### Git workflow

```bash
make ensure-branch BRANCH=develop
make commit BRANCH=develop GIT_COMMIT_MESSAGE="feat: update startup flow"
make push BRANCH=develop
make git-sync BRANCH=develop GIT_COMMIT_MESSAGE="feat: update startup flow"
```

### Безопасность

```bash
make security-check
make deps-check
make secrets-check
make audit
```

### Docker

```bash
make docker-build
make docker-run
make docker-stop
```

## Docker-запуск

### Сборка образа

```bash
make docker-build
```

### Запуск контейнера

```bash
make docker-run
```

Контейнер запускает проект через `scripts/manage.sh run`.

## Доступные сервисы

После запуска будут доступны:

- FastAPI: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Prefect UI: `http://localhost:4200`

## RabbitMQ и миграции

### Инициализация RabbitMQ

```bash
make rabbit-init
```

### Применение миграций

```bash
make migrate
```

## Логирование и runtime-файлы

Во время работы проекта используются:

- `logs/` — runtime-логи сервисов
- `.run/` — PID и runtime-артефакты

Эти каталоги не должны попадать в Git.

## Разработка

Инструменты разработки:

- `black`
- `isort`
- `flake8`
- `mypy`
- `bandit`
- `deptry`
- `trufflehog`
- `pip-audit` (опционально, через Nexus)

Примеры:

```bash
make code-lint
make code-check
```

Если нужен `pip-audit` через внутренний Nexus:

```bash
make code-check PIP_AUDIT=1 NEXUS_HOST=nexus.bank.srv NEXUS_PYPI_URL="https://nexus.bank.srv/repository/pypi/simple"
```

## Примечания

- Для локального запуска основная точка управления — `Makefile`
- Для runtime-оркестрации основная точка — `scripts/manage.sh`
- Для контейнера используется `Dockerfile`, который запускает `scripts/manage.sh`

## Автор

**crazyivan1289**

## Статус

В разработке
