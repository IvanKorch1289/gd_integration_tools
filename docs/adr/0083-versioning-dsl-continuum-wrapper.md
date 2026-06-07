# ADR-0083 — Row-Level Versioning: thin DSL wrapper над `sqlalchemy-continuum`

**Status:** Accepted
**Date:** 2026-06-07
**Authors:** K3
**Sources:** S58 W1, PLAN.md V22.5 §S58 adr-w3
**Supersedes:** N/A (new ADR)

---

## Context

S58 phase-0 reconnaissance обнаружил dormant state `sqlalchemy-continuum`:

- `sqlalchemy-continuum>=1.5.2,<2.0.0` в core dependencies (`pyproject.toml` line 31)
- `make_versioned(plugins=[ActivityPlugin(), PropertyModTrackerPlugin()])` вызван в `src/backend/infrastructure/database/models/base.py`
- `__versioned__ = {}` на `BaseModel` (auto-включает versioning для всех concrete subclasses, если не override `__versioned__ = {"versioning": False}`)
- Version tables (`users_version`, `files_version`, `orderfiles_version`, `orderkinds_version`, `orders_version`, `transaction`, `activity`) **уже созданы** в init migration `2025_03_10_1637-20036813ff7c_.py`
- 7 моделей (User, CertRecord, File, OrderKind, Order, RuleEngineBase, LangMemEpisodic) **должны быть** versioned, но фактически version rows не создаются при INSERT/UPDATE в production runtime

Pre-existing perception "continuum сломан" был self-inflicted: `version_class_map` заполняется на `after_configured` event, который срабатывает от `configure_mappers()` (явный вызов) или implicit от первого session creation / query execution. В production runtime при первом `session.add()` / `session.execute()` всё работает, но разработчики не знали об этом и избегали `version_class(model)` (он бросал `ClassNotVersioned` до первого query).

Pre-S58 попытки решить задачу шли по wrong path:
- v15–v17 рекомендовали реализовать кастомный `EntityAuditLog` (JSONB single-table) — конфликт с проектным правилом "libraries > custom"
- v18–v19 рекомендовали мигрировать на `purgatory` (нет) и другие audit-библиотеки — overkill
- v21 (S55 context) предлагал `VersioningMixin` с custom event listeners — те же проблемы

## Decision

**Использовать `sqlalchemy-continuum` для row-level history + тонкий DSL-facade `src/backend/dsl/audit_versioning.py` для высокоуровневого API.**

DSL facade (252 LOC) предоставляет:
- `Versioning.get_history(session, model, id)` — все версии сущности, ordered by `transaction_id` ASC
- `Versioning.get_version(session, model, id, tx_id)` — конкретная версия или `None`
- `Versioning.rollback(session, model, id, tx_id)` — restore к состоянию из конкретной версии (создаёт новую version row через continuum auto-tracking)
- `Versioning.diff(session, model, id, tx1, tx2)` — per-column changes между двумя версиями (old/new dict) + operation names
- `VersioningError` — единый DSL exception type (re-raise `sqlalchemy_continuum.exc.ClassNotVersioned` для consistency)

DSL НЕ дублирует логику continuum:
- Continuum manages: `*_version` tables, `transaction` table, `activity` table, mod tracking (`username_mod`, `email_mod`, ...), property change detection через `sqlalchemy.orm.attributes.get_history()`
- DSL делает ТОЛЬКО: query API + structured diff output + exception translation

## Контракт (DSL API)

```python
from src.backend.dsl.audit_versioning import Versioning, VersioningError

# 1. История всех изменений
history = Versioning.get_history(session, User, 42)
# → [UserVersion(tx=1, op=INSERT, name='alice', email='a@x.com'),
#    UserVersion(tx=2, op=UPDATE, name='alice2', email='a2@x.com')]

# 2. Конкретная версия
v1 = Versioning.get_version(session, User, 42, transaction_id=1)

# 3. Rollback (continuum auto-tracks как новую UPDATE)
Versioning.rollback(session, User, 42, transaction_id=1)
session.commit()  # → новая version row tx=N+1 с состоянием из tx=1

# 4. Diff между версиями
diff = Versioning.diff(session, User, 42, tx_id_1=1, tx_id_2=3)
# → {"entity": "User#42",
#    "from_transaction": 1, "to_transaction": 3,
#    "from_operation": "INSERT", "to_operation": "UPDATE",
#    "changes": {"email": {"old": "a@x.com", "new": "a2@x.com"}}}
```

## Requirements для модели

Модель **должна** иметь `__versioned__ = {}` (inherited from `BaseModel` by default) **И** наследоваться от `BaseModel` (НЕ от абстрактного mixin).

Модель **НЕ должна** иметь `__versioned__ = {"versioning": False}` (opt-out для служебных таблиц: outbox, dsl_snapshot, workflow_event, workflow_instance).

Применяется через **explicit declaration** в модели. `Versioning` НЕ предоставляет `VersionedMixin` — нативный `__versioned__` continuum достаточно explicit (continuum internal API).

## Альтернативы Evaluated

| Подход | Trade-offs | Decision |
|--------|-----------|----------|
| **Custom `EntityAuditLog` (JSONB single-table)** | ~600 LOC кастомного event-listener кода, дублирует `get_history` от continuum, конфликт с project rule "libraries > custom" | ❌ Rejected |
| **`purgatory` + custom event listeners** | Меньше LOC чем custom, но purgatory = request-response tracking, не row history | ❌ Rejected (wrong domain) |
| **Миграция на `sqlalchemy-history` / `sqlalchemy-versioned` (другие либы)** | Меньше community support, дублирует continuum feature set | ❌ Rejected (no advantage) |
| **Direct `sqlalchemy-continuum` без DSL** | Работает, но `version_class(model)` возвращает raw model, нет structured diff, no exception translation, callers повторяют boilerplate | ❌ Rejected (DSL value-add) |
| **DSL facade (chosen)** | 252 LOC, единый API, structured output, exception translation, future-proof (можно мигрировать underlying lib без breaking changes) | ✅ **Selected** |

## Implementation Details

### Файлы

- `src/backend/dsl/audit_versioning.py` — 252 LOC, DSL facade
- `tests/unit/dsl/test_audit_versioning.py` — 314 LOC, 13 tests

### Скрытые дефолты

- `OP_INSERT = 0`, `OP_UPDATE = 1`, `OP_DELETE = 2` — константы continuum (`sqlalchemy_continuum.operation`); exposed в DSL для тестов
- `_SKIP_COLUMNS = {id, transaction_id, end_transaction_id, operation_type, created_at, updated_at}` — managed by continuum/ORM, не копируются при rollback
- `_CONTEXT_COLUMNS = {id, transaction_id, operation_type, end_transaction_id}` — не показываются в diff (managed by continuum)

### Continuum setup — без изменений

`base.py` остаётся как есть:
```python
make_versioned(user_cls=None, plugins=[ActivityPlugin(), PropertyModTrackerPlugin()])
# ...
class BaseModel(AsyncAttrs, Base):
    __abstract__ = True
    __versioned__ = {}  # Включает versioning для всех concrete subclasses
```

`user_cls=None` важен: default = 'User' string → continuum tries to find 'User' class in registry → `ImproperlyConfigured: Could not build relationship between Transaction and User`. С `user_cls=None` relationship скипается.

## Verification

```bash
# Verify version_class(User) works after configure_mappers
python -c "
from sqlalchemy.orm import configure_mappers
from src.backend.infrastructure.database.models.base import Base
import src.backend.infrastructure.database.models.users as u
from sqlalchemy_continuum import version_class
configure_mappers()
UV = version_class(u.User)
assert UV.__table__.name == 'users_version'
print('OK: UserVersion table:', UV.__table__.name)
"

# Verify end-to-end INSERT/UPDATE creates version rows
pytest tests/unit/dsl/test_audit_versioning.py -v
# → 13 passed in 0.45s
```

## Open Items

- **S59+** (backlog): Migrate 6 dormant models to actually use versioning (User/CertRecord/File/OrderKind/Order/RuleEngineBase/LangMemEpisodic). S58 W4 = apply к User как proof-of-concept.
- **S59+** (backlog): 606 файлов используют `import logging` напрямую — structlog migration (ADR-0084 покрывает scope)
- **S59+** (backlog): Custom retention policy (continuum 1.6.0 не имеет встроенного; нужен cron-job для `DELETE FROM transaction WHERE issued_at < NOW() - INTERVAL '90 days'`)

## Relation to Other ADRs

- **ADR-001** (Layer Boundaries): `__versioned__` enforcement происходит на SQLAlchemy mapper level, не нарушает layer boundaries
- **ADR-0050** (WAF + OutboundHttpClient): Оба используют `__versioned__ = {}` из BaseModel (default), могут query history через DSL facade
- **S57 W2** (libraries migration): structlog + typer + rich + aiocache — ADR-0084 покрывает scope
- **S55 W1** (VersioningMixin предложение): superseded этим ADR
