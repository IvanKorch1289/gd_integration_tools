# Runbook — DB Migration

Безопасное применение Alembic-миграций.

## Symptom
- В PR — новая `migrations/versions/*`.
- Перед/после релиза нужно обновить схему.

## Cause
Плановое изменение схемы.

## Resolution
1. **Бэкап** перед миграцией: `pg_dump` → S3.
2. Запустить миграцию:
   `make migrate` (Alembic upgrade head).
3. Для долгих миграций — выполнить за окно maintenance:
   - `lock_timeout = 5s`;
   - `idx_concurrently` для индексов.
4. Прогнать `make readiness-check` после.

## Verification
- `alembic current` показывает свежий `head`.
- `make routes`, `make actions` без ошибок.
- 5xx-rate не вырос.

## Rollback
1. `alembic downgrade -1` (если миграция атомарна).
2. Если необратима — restore из `pg_dump` (RTO ≈ 30 мин).
3. Сообщить в `#ops` о rollback'е миграции.
