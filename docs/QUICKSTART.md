# QUICKSTART — быстрый старт без Docker

**Цель**: поднять gd_integration_tools локально без Docker / без тяжёлой
инфраструктуры (Postgres / Redis / Mongo / S3 / Vault / Kafka /
Elasticsearch / ClickHouse) — для разработки, отладки DSL-маршрутов и
смок-проверки изменений.

Профиль `dev_light` уважает контракт `Wave 21` —
`APP_PROFILE=dev_light` переключает все backend'ы на легковесные
аналоги:

| Production-компонент | dev_light fallback |
|---|---|
| PostgreSQL | SQLite (через aiosqlite) |
| Redis | пропускается (`redis.enabled=false`) |
| RabbitMQ | пропускается (`queue.enabled=false`) |
| MongoDB | пропускается (`mongo.enabled=false`) |
| MinIO / S3 | LocalFS (`fs.provider=local`) |
| Vault | пропускается, секреты из `.env` |
| Kafka | пропускается (нет `settings.kafka`) |
| Elasticsearch | пропускается (`elasticsearch.enabled=false`) |
| ClickHouse | пропускается (`clickhouse.enabled=false`) |
| Graylog | отключён (`log.host=""`) |
| Внешние БД (Oracle/PG из Vault) | пустой список |

---

## Требования

- **Python 3.14+** (см. `pyproject.toml::requires-python`).
- **uv** (`https://docs.astral.sh/uv/`) — менеджер зависимостей.
- Любая ОС с unix-shell (Linux / macOS / WSL).

---

## 1. Установка зависимостей

```bash
git clone <repo-url> gd_integration_tools
cd gd_integration_tools
uv sync --extra dev-light
```

Группа `dev-light` поверх стандартного `[project.dependencies]`
доустанавливает только `aiosqlite` — он нужен для SQLite-DSN. Никаких
тяжёлых extras (`ai`, `rpa-*`, `iot`) не подтягивается.

---

## 2. Запуск backend'а

### Через Makefile (рекомендуется)

```bash
make dev-light
```

Эквивалент:

```bash
APP_PROFILE=dev_light APP_SERVER=uvicorn uv run python manage.py run
```

Сервис стартует на `http://127.0.0.1:8000` (host/port настраиваются
через `APP_HOST` / `APP_PORT`).

### Без Makefile

```bash
APP_PROFILE=dev_light \
  uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

---

## 3. Проверка `/health`

```bash
curl http://127.0.0.1:8000/health
# → {"status":"alive","version":"0.1.0"}    HTTP 200
```

`/health` — liveness probe (event loop отвечает). Не зависит от
backend'ов.

```bash
curl http://127.0.0.1:8000/ready
# → агрегированный отчёт (database/redis/s3 ...)
```

`/ready` — readiness probe. На `dev_light` некоторые компоненты
ожидаемо degraded (Redis/S3 отключены) — это нормально для локального
стенда. Если все компоненты `ok` → `200`, иначе `503` с подробностями.

---

## 4. Запуск Streamlit-фронта

```bash
make frontend
# или вручную:
uv run python manage.py run-frontend --port 8501
```

Дашборд доступен на `http://127.0.0.1:8501`. Большинство страниц
корректно отрабатывают со связкой `dev_light` (SQLite). Страницы,
требующие Redis / Mongo / S3 / Kafka, отображают предупреждение —
это ожидаемо.

---

## 5. Профили

`APP_PROFILE` определяет набор backend'ов:

| Profile | Назначение | Подгружается из |
|---|---|---|
| `dev` (default) | Полный стенд с Docker compose | `config_profiles/dev.yml` (полный baseline) |
| `dev_light` | Без Docker, всё в SQLite/память | `dev.yml` + `dev_light.yml` overlay |
| `staging` | Pre-production | `dev.yml` + `staging.yml` overlay |
| `prod` | Production | `dev.yml` + `prod.yml` overlay |

Логика loader-а: base = `config_profiles/dev.yml`; если активный
профиль ≠ dev — поверх deep-merge накладывается
`config_profiles/{profile}.yml`. См.
`src/core/config/config_loader.py::YamlConfigSettingsLoader`.

Чтобы переопределить отдельные ключи без правки overlay-файла —
используйте env-переменные: для каждой группы settings `env_prefix`
указан в `model_config` (например, `REDIS_HOST`, `DATABASE_HOST`).

---

## 6. Минимальный smoke-тест

```bash
APP_PROFILE=dev_light uv run uvicorn src.main:app --port 18000 &
sleep 5
curl -fs http://127.0.0.1:18000/health   # → 200 alive
curl -fs http://127.0.0.1:18000/openapi.json | head -c 100
kill %1
```

---

## 7. Что НЕ работает на dev_light

- **Endpoint'ы, явно требующие Redis / Mongo / S3 / Kafka / Vault**
  отвечают `503` или `400` с понятной ошибкой (контракт сохранён).
- **APScheduler с durable jobstore** работает на SQLite, но **outbox
  worker** недоступен (нужен Kafka/Rabbit) — лог пишет warning, не
  блокирует старт.
- **AI-агенты с LiteLLM/Langfuse** требуют `--extra ai` и реальных
  ключей провайдеров.
- **RPA browsers / OCR** требуют `--extra rpa-*` и системных пакетов
  (Playwright / Tesseract).

---

## 8. Прод-запуск

```bash
APP_PROFILE=prod APP_SERVER=granian uv run python manage.py run
# или make prod
```

Granian заменяет uvicorn в prod (см. `Dockerfile`, ADR-006/007).
`config_profiles/prod.yml` — overlay с production-флагами;
секреты/хосты приходят из env / Vault, не из YAML.

---

## 9. Полезные команды

```bash
make help                # список целей
make routes              # список DSL-маршрутов
make actions             # реестр action-обработчиков
make lint                # ruff + mypy (soft)
make lint-strict         # ruff + mypy (strict)
make layers              # layer linter (ADR-001)
make migrate             # alembic upgrade head (только для PG)
make test                # pytest (unit + integration)
```

> **Замечание про `make routes` / `make actions`**: цели запускают
> `_bootstrap()` `manage.py`, который импортирует БД-драйвер из активного
> профиля. Если БД в `.env` указывает на PostgreSQL без суффикса
> `+asyncpg` — будет требоваться синхронный `psycopg2` (не входит в
> `dev-light`). Решения: (1) использовать `postgresql+asyncpg://` URL,
> (2) запускать с `APP_PROFILE=dev_light` (SQLite + `aiosqlite`),
> (3) `uv sync --extra prod` если действительно нужен PG-драйвер для
> CLI-интроспекции.

---

## 10. Связанные документы

- `ARCHITECTURE.md` — архитектура слоёв (entrypoints / services / core /
  infrastructure).
- `DEVELOPER_GUIDE.md` — гайд для разработчика.
- `DEPLOYMENT.md` — production-развёртывание.
- `DSL_COOKBOOK.md` — рецепты DSL-маршрутов.
- `adr/` — Architecture Decision Records (ADR-001 ... ADR-032).
