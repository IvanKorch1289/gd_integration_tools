```markdown
# GD Advanced Tools

API-Шлюз для интеграции с API СКБ-Техно и DaData с расширенными возможностями.

[![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python&logoColor=white)](https://python.org)  
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.2-blue?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)  
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-blue?logo=postgresql&logoColor=white)](https://postgresql.org)  
[![Redis](https://img.shields.io/badge/Redis-7+-red?logo=redis&logoColor=white)](https://redis.io)  
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## Основные возможности

- 🚀 Асинхронное API на FastAPI
- 🔒 Управление лимитами запросов через Redis
- 📊 Интеграция с Graylog для централизованного логирования
- 🗄️ Асинхронный доступ к PostgreSQL через SQLAlchemy 2.0
- 📧 Работа с SMTP-сервером для отправки уведомлений
- 🗂️ Хранение файлов в MinIO
- 🐇 Интеграция с RabbitMQ через FastStream
- ⏰ Планирование задач через APScheduler
- 🔄 Сложные workflow с Prefect
- 📈 Мониторинг метрик через Prometheus
- 🔍 Трассировка запросов с OpenTelemetry

## Используемые технологии

![Stack](https://skillicons.dev/icons?i=fastapi,postgresql,redis,rabbitmq,docker,grafana,prometheus)

## Установка

1. Установите Poetry:

    ```bash
    curl -sSL https://install.python-poetry.org | python3 -
    ```

2. Установите зависимости:

    ```bash
    poetry install --no-root
    ```

3. Настройте переменные окружения:

    ```bash
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
    LOG_ROOT_PASSWORD_SHA2=5
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

## Запуск

Запустите скрипт:

```bash
./start.sh
```

Документация API будет доступна по адресу: [http://localhost:8000/docs](http://localhost:8000/docs)

## Мониторинг и логирование

- Prometheus метрики: `/metrics`
- Grafana dashboard: пример в `monitoring/grafana`
- Graylog: настройка через GELF handler

## Лимиты запросов

Система лимитов реализована через:

- `fastapi-limiter` для rate-limiting
- Redis для хранения счетчиков
- Кастомные политики для разных эндпоинтов

## Безопасность

- Статический анализ кода: `bandit`, `trufflehog`
- Проверка зависимостей: `safety`
- Хранение секретов: HashiCorp Vault (hvac)

## Разработка

Инструменты:

- Форматирование: `black`, `isort`
- Линтинг: `flake8`, `pylint`
- Типизация: `mypy`
- Профилирование: `memray`, `py-spy`

Запуск проверок:

```bash
make lint  # Запуск всех проверок
make format  # Автоформатирование кода
make test  # Запуск тестов (добавьте свои тесты)
```

Автор: **crazyivan1289**  
Версия: **1.0.0**  
Статус: **В разработке**
```