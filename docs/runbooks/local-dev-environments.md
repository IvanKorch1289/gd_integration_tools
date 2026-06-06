# Local Dev Environments — Light vs Full Stack

**Sprint 54 W2**. Two compose-стенда для локальной разработки + CI:

| Стенд | Состав | Когда использовать | Makefile target |
|-------|--------|--------------------|-----------------|
| **Light** | app + worker (no infra) | Быстрый smoke-test, разработка без БД, CI | `make up-light` |
| **Full** | app + worker + postgres + redis + clamav | Полный E2E, миграции, multi-tenant | `make up-full` |
| **Plugin-Dev** | postgres + redis (no app) | Разработка plugins в изоляции | `make up-plugin-dev` |

---

## Light Stack

### Что поднимается
- `app` (gd-app-light) — FastAPI/Granian на :8000
- `workflow-worker` (gd-worker-light) — Temporal-lite executor

### Что НЕ поднимается
- ❌ PostgreSQL — `dev_light` profile использует SQLite (`./.run/dev_light.db`)
- ❌ Redis — in-memory cache
- ❌ ClamAV — antivirus выключен (`AV_MODE=disabled`)
- ❌ Migration runner — Alembic не нужен для SQLite in dev_light

### Когда НЕ работает
Light stack **не подходит** для:
- multi-tenant tests (требует Postgres RLS)
- DDL-heavy features (DBA migrations)
- production smoke (нет ClamAV → uploads bypass AV scan)
- integration tests с реальными external APIs

### Запуск

```bash
# Из корня репозитория:
make up-light

# Проверить статус:
make ps-light

# Логи:
make logs-light

# Остановить:
make down-light
```

App доступен на http://localhost:8000.

### Volumes
- `./.run:/app/.run` — bind mount, persists SQLite DB, logs, runtime state
  между перезапусками контейнера.

---

## Full Stack

### Что поднимается
- `migration-runner` — Alembic upgrade head (one-shot)
- `app` — FastAPI/Granian на :8000
- `workflow-worker` — Temporal executor (4 replicas)
- `postgres` — PostgreSQL 16 (port 5432)
- `redis` — Redis 7 (port 6379)
- `clamav` — ClamAV antivirus (port 3310)

### Когда использовать
- Integration tests
- Performance benchmarking
- Production-like smoke tests
- Multi-tenant scenarios

### Запуск

```bash
make up-full
make ps-full
make logs-full
make down-full
```

### Health checks
- Postgres: `pg_isready` (5s interval)
- Redis: `redis-cli ping` (5s interval)
- ClamAV: TCP `PING` → `PONG` (30s interval, 120s start_period для загрузки signatures)

### Volumes (named, persistent)
- `pgdata` — Postgres data
- `redisdata` — Redis AOF
- `clamav_db` — ClamAV signature database

⚠️ **Удаление volumes** = потеря данных. Используйте `make clean-volumes` с подтверждением.

---

## Plugin-Dev Stack

### Что поднимается
- `postgres` (port 5433, чтобы не конфликтовать с full stack на 5432)
- `redis` (port 6380)

### Когда использовать
- Разработка plugins с hot-reload (без app контейнера)
- Тестирование миграций
- Debugging БД-issues без overhead app

### Запуск

```bash
make up-plugin-dev
# Подключиться к Postgres: psql -h localhost -p 5433 -U gd -d gd_dev
# Redis: redis-cli -h localhost -p 6380
make down-plugin-dev
```

---

## Troubleshooting

### Light stack: "address already in use" на :8000

Локальный uvicorn/granian уже слушает порт. Остановите его:
```bash
lsof -ti:8000 | xargs kill -9
make restart-light
```

### Full stack: postgres healthcheck fails

Подождите 10-20s (cold start). Если не помогает:
```bash
docker compose -f ops/compose/docker-compose.yml logs postgres
make restart-full
```

### ClamAV: clamd startup timeout (300s exceeded)

ClamAV качает signatures при первом старте. Может занять 5-10 минут.
Подождите или pre-warm:
```bash
docker exec -it $(docker compose -f ops/compose/docker-compose.yml ps -q clamav) freshclam
```

### "Permission denied" на `./.run` (light stack)

`./.run` создаётся с правами текущего пользователя. Если запускали
ранее от root, исправьте:
```bash
sudo chown -R $USER:$USER ./.run
```

### Secrets в .env показываются в `docker compose config`

⚠️ Никогда не коммитьте вывод `docker compose config` — содержит
реальные credentials из `.env`. Для отладки используйте:
```bash
docker compose -f ops/compose/docker-compose.light.yml config --quiet  # only structure
```

---

## CI Integration

Рекомендуемый pipeline:
1. **Lint + unit tests** (no Docker) — `make lint test`
2. **Light stack smoke** — `make up-light && curl localhost:8000/health && make down-light`
3. **Full stack integration** — `make up-full && pytest tests/integration && make down-full`
4. **Plugin-dev isolation** — `make up-plugin-dev && pytest tests/plugins/ && make down-plugin-dev`

Light stack поднимается за ~10-20s (нет postgres init), full за ~60-90s
(postgres init + clamav signatures). Используйте light для speed-critical
CI jobs.

---

## Связанные документы

- `docs/runbooks/disaster_recovery.md` — disaster recovery
- `docs/runbooks/blue-green-rollback.md` — production deployment
- `docs/runbooks/extension-deploy.md` — plugin deployment
- `config_profiles/dev_light.yml` — light profile settings
- `config_profiles/dev.yml` — full dev profile settings
