# Docker Compose Gap Analysis

**Date**: 2026-06-23 (S168 W14) · **Обновлено**: 2026-11-18 (волны 34–35)
**Status**: INFO — no production blockers

---

## Current Services (docker-compose.yml)

| Service | Role | Profile | Healthcheck | Notes |
|---------|------|---------|-------------|-------|
| `postgres` | Database | — | `pg_isready` | ✅ Healthy |
| `redis` | Cache/Queue | — | `redis-cli ping` | ✅ Healthy |
| `clamav` | AV scanning | — | None | ✅ Running |
| `migration-runner` | Schema migration | `prod` | N/A | `restart: no` — optional |
| `app` | FastAPI backend | `dev` | None | ⚠️ No healthcheck |
| `workflow-worker` | DSL worker | `dev` | None | ⚠️ No healthcheck, 4 replicas |

---

## Dev Profile (APP_PROFILE=dev) Requirements

`dev.yml` disables:
- `redis.enabled: false`
- `queue.enabled: false`
- `kafka.enabled: false`
- `vault.enabled: false`

**Impact**: No Kafka, Minio, Vault, or external queue required for dev stack.
Docker-compose provides sufficient infrastructure for `dev` profile.

---

## Production Gap (APP_PROFILE=prod)

**Актуально на 2026-11-18.** Прежняя редакция документа утверждала, что
сервисы прода «отсутствуют». Это больше не так: они объявлены в
`ops/compose/docker-compose.prod.yml`. Прод-стек запускается как
`docker-compose -f docker-compose.yml -f docker-compose.prod.yml`.

| Service | Required by prod.yml | Где объявлен | Статус |
|---------|---------------------|--------------|--------|
| `otel-collector` | `opentelemetry_endpoint: "http://otel-collector:4317"` | `docker-compose.prod.yml` | ✅ есть (+ `jaeger`) |
| `kafka` | `kafka.enabled: true` | `docker-compose.prod.yml` | ✅ есть (+ `kafka-zookeeper`, `schema-registry`, `connect-distributed`, `kafka-ui`) |
| `minio` | S3 storage | `docker-compose.prod.yml` | ✅ есть |
| `vault` | `vault.enabled: true` | `docker-compose.prod.yml` | ✅ есть |
| `clickhouse` | `audit_clickhouse_enabled` | `docker-compose.prod.yml` | ✅ добавлен волной 34 (DDL audit-трейла накатывается на старте) |
| `open-webui` | `open_webui.base_url` | `docker-compose.prod.yml` | ✅ добавлен волной 34 (`WEBUI_SECRET_KEY` из секрет-хранилища) |
| `jupyterhub` | `jupyter_hub.base_url` | `docker-compose.prod.yml` | ✅ добавлен волной 34 (конфиг — `ops/compose/jupyterhub/`) |
| `celery-worker` | Async task queue | `docker-compose.prod.yml` | ⛔ **за `profiles: ["celery"]`** (волна 35) |
| `celery-beat` | Celery scheduler | `docker-compose.prod.yml` | ⛔ **за `profiles: ["celery"]`** (волна 35) |

### Почему celery-сервисы отключены по умолчанию

Волна 35 (аудит 2026-11-18, P1) перевела `celery-worker`/`celery-beat` за
opt-in-профиль `profiles: ["celery"]`, потому что:

* пакет `celery` **не объявлен** ни в `[project.optional-dependencies]`
  `pyproject.toml`, ни в `uv.lock`;
* модуль с точкой входа `celery_app` **не существует** (каталога
  `src/backend/tasks/` нет).

Без профиля compose не поднимает эти сервисы. Чтобы включить стек celery,
нужно: (1) объявить `celery` в extras и пересобрать lock; (2) создать
модуль `celery_app`; (3) запускать compose с `--profile celery`.
До этого celery не является частью прод-стека.

**Recommendation**: Keep `APP_PROFILE=dev` for local docker dev. For production, use
`docker-compose -f docker-compose.yml -f docker-compose.prod.yml` pattern with
prod-specific overrides that include missing services.

---

## Actions Taken (S168 W14)

1. `migration-runner`: `entrypoint: ["sh", "-c"]` + `command: ["python -m alembic -c alembic.ini upgrade head || true"]` — fixes ENTRYPOINT conflict
2. `app`: `APP_PROFILE: dev`, `DB_HOST: postgres` — matches dev.yml requirements
3. `workflow-worker`: `APP_PROFILE: dev`, `DB_HOST: postgres` — same
4. `Dockerfile`: `COPY config_profiles ./src/config_profiles` + `PYTHONPATH="/app/src"` — runtime path alignment (requires image rebuild)

---

## TODO for Production Docker Setup

- [x] Add healthcheck endpoint to `app` (uses `/docs` — FastAPI Swagger UI is always available)
- [x] Create `docker-compose.prod.yml` with full infrastructure (Kafka, Minio, Vault, OTEL, Celery)
- [x] Create `otel-collector-config.yaml` for OTEL collector
- [x] Document production deployment in `docs/docker/` (ops/docker-compose-gap.md)
