# NEW-16: orders.list fails on light-profile (no sqlite migrations)

**HEAD**: `2532c9b` (cycle 205)
**Агент**: Kimi Code CLI, swarm mode
**Date**: 2026-08-14

## Bug

`GET /api/v1/auto/orders.list` в light-profile (sqlite) returns **500 Internal Server Error**:
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: orders
```

## Root Cause

`OrderRepository` SQLAlchemy model определён с relationships к:
- `orderkinds` (FK на order_kind_id)
- `orderfiles` → `files` (many-to-many via `orderfiles`)

При `JOIN`-стратегии SQLAlchemy `selectinload` или `joinedload`, ORM генерирует:
```sql
SELECT orders.*, orderkinds.*, files.*
FROM orders LEFT OUTER JOIN orderkinds ... LEFT OUTER JOIN (orderfiles JOIN files) ...
```

В light-profile sqlite БД нет ни одной из этих таблиц — миграции Alembic не были применены к `.run/dev.sqlite3`.

## Impact

- `orders.list` не работает в light-profile
- Аналогичные endpoints (orders.add, orders.update) тоже могут падать
- Невозможно полноценно тестировать бизнес-функциональность в dev_light

## Fix (multi-session, требует решения пользователя)

**Вариант A**: Применить Alembic миграции к light sqlite при startup
```bash
# В docker-compose.light.yml:
command: >
  sh -c "alembic upgrade head && <existing command>"
```

**Вариант B**: Создать отдельную sqlite schema для dev_light (только core-таблицы)
```python
# src/backend/core/database/migrations/versions/dev_light_*.py
- create only essential tables (no orderkinds, no orderfiles)
```

**Вариант C**: Profile-aware модель — `if profile == "dev_light": return no relationships`
```python
# src/backend/services/io/orders/services/orders.py
@property
def _relationships_enabled(self) -> bool:
    return get_active_profile().value != "dev_light"
```

## Рекомендация

**Вариант A** (apply migrations) — проще, consistent с dev/prod behavior.

## Production readiness impact

- Light-profile не функционален для orders-related endpoints
- Frontend, Streamlit pages, orders тестирование — заблокировано
- 90% readiness requires this fix

## Multi-session backlog

| ID | Effort | Status |
|---|---|---|
| Apply migrations to light sqlite | 1-2 hours | pending |
| Profile-aware models | 3-5 days | pending |
