# Runbook — Deploy

Стандартный production-деплой gd_integration_tools.

## Symptom
Готова новая версия (`master`/`release/*`) — нужно выкатить её в prod без даунтайма.

## Cause
Плановый релиз. Не относится к incident-flow.

## Resolution

1. Убедиться, что CI зелёный: `make check-strict-full` локально.
2. `git tag vX.Y.Z` (или `make bump`).
3. `make docker-build` → push образа в registry.
4. Применить миграции: `make migrate` против целевой БД.
5. Перезапуск сервиса:
   ```bash
   APP_PROFILE=prod APP_SERVER=granian make run
   ```
6. Дать healthcheck подняться: `curl /api/v1/health/ready`.

## Verification
- `curl /api/v1/health/live` → 200.
- `curl /api/v1/health/ready` → 200.
- Грубый smoke: `curl /api/v1/actions/inventory` возвращает ≥ 100 actions.
- Метрики не показывают всплеска ошибок в первые 5 минут.

## Rollback
1. Откат образа: redeploy предыдущего тега.
2. Если миграция несовместима — `alembic downgrade -1`.
3. Подтвердить через `/health/ready` + actions count.
