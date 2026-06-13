# D5 Migration Plan: SQLAlchemy models → `core/domain/models/`

**Status:** S105 W1 — план (analysis-only). Реальный перенос — multi-sprint.
**Source:** DEEP-RESEARCH D5 (🔴 High), S103 W1 linter (41 violations), S94 W1-W2
**Author:** S105 subagent
**Sprint window:** S104 closure (2026-06-13) → S105+ (multi-sprint execution)

---

## 1. Проблема

Extensions (`extensions/<name>/`) импортируют SQLAlchemy ORM-модели из
`src.backend.infrastructure.database.models.*` для repository/services/
workflows. Это нарушает layer policy:

> `extensions/` → только `gd_integration_tools.{core, testkit}` +
> capability-checked фасады. Прямой импорт из `infrastructure/*` запрещён.

**Measured (S103 W1):**

| Категория | Файлов | Примеры |
|-----------|--------|---------|
| `domain/models.py` (ORM) | 5 | `from src.backend.infrastructure.database.models import Order` |
| `repositories/*` | 8 | `from src.backend.infrastructure.database.models.users import User` |
| `services/*` | 16 | импорты моделей для typed DTO |
| `workflows/*` | 12 | импорты моделей для Temporal input |
| **Total** | **41** | (vs DEEP-RESEARCH claim 20 — S103 W1 honest measurement) |

**Корневая причина:** SQLAlchemy models живут в `infrastructure/`, а extensions
обязаны импортировать их для ORM-операций. Архитектурно правильное место —
`core/domain/models/` (domain-agnostic, импортируется extensions).

---

## 2. Текущая структура (12 model files + 1 namespace marker)

| Файл | LOC | Base | Tenant | FK | Enum | Risk |
|------|-----|------|--------|----|----|------|
| `base.py` | 94 | — | — | — | — | **carrier** (continuum init) |
| `cert.py` | 60 | Base (не BaseModel) | ✗ | ✗ | ✗ | A |
| `dsl_snapshot.py` | 62 | BaseModel | ✓ | ✗ | ✗ | A |
| `files.py` | 63 | BaseModel + Base | ✓ | FK→orders, FK→files | ✗ | **B** (через OrderFile) |
| `langmem_models.py` | 67 | Base | ✗ | ✗ | ✗ | A |
| `orderkinds.py` | 38 | BaseModel | ✓ | rel→Order | ✗ | B |
| `orders.py` | 67 | BaseModel | ✓ | FK→orderkinds | ✗ | **B** |
| `outbox.py` | 74 | BaseModel | ✗ | ✗ | ✗ | A |
| `rule_engine.py` | 74 | изолированный `RuleEngineBase` | ✗ | ✗ | ✗ | A (decoupled) |
| `users.py` | 84 | BaseModel | ✓ | ✗ | ✗ | A |
| `workflow_event.py` | 158 | BaseModel | ✓ | FK→workflow_instances | WorkflowEventType | **C** (cross-BaseModel+Enum) |
| `workflow_instance.py` | 154 | BaseModel | ✓ | ✗ | WorkflowStatus | **C** (Enum) |

**Total:** 12 model files + `__init__.py` namespace marker.

---

## 3. Целевая структура

```
src/backend/core/domain/models/
├── __init__.py                # re-export canonical
├── base.py                    # BaseModel, metadata (carrier)
├── cert.py                    # Risk A
├── dsl_snapshot.py            # Risk A
├── files.py                   # Risk B
├── langmem_models.py          # Risk A
├── orderkinds.py              # Risk B
├── orders.py                  # Risk B
├── outbox.py                  # Risk A
├── rule_engine.py             # Risk A (с явной note об изоляции от BaseModel)
├── users.py                   # Risk A
├── workflow_event.py          # Risk C
└── workflow_instance.py       # Risk C
```

**Back-compat shim (1 sprint grace):**

```
src/backend/infrastructure/database/models/
├── __init__.py                # DeprecationWarning, re-export
├── base.py                    # from src.backend.core.domain.models.base import *
├── cert.py                    # shim
├── ... (12 файлов shim'ов)
```

Паттерн shim — аналог `core/audit/facade.py` (S103 W3 facade):
- `infrastructure/database/models/<name>.py` = `from src.backend.core.domain.models.<name> import *`
- `DeprecationWarning` при импорте.
- `tools/check_layers.py --root extensions` — не учитывает shim imports как violations (whitelist).
- Hard delete через 1 sprint (S106 W1).

---

## 4. Batch-план (B1, B2, B3 по риску)

### B1 — Risk A (6 файлов, ~520 LOC)

`cert.py`, `dsl_snapshot.py`, `langmem_models.py`, `outbox.py`, `rule_engine.py`, `users.py`.

Нет FK chain, нет enum'ов, нет cross-schema dependencies. Можно делать
атомарно в одной сессии. Минимальный blast radius.

**Шаги:**
1. Создать `src/backend/core/domain/models/` с `__init__.py`.
2. `git mv` 6 файлов в новое местоположение.
3. Создать shim'ы в `infrastructure/database/models/`.
4. Обновить `tools/check_layers.py` — добавить shim whitelist.
5. Прогнать `pytest tests/unit/infrastructure/database/ -x` — должно пройти без изменений.
6. Commit: `refactor(s105-b1-d5): move Risk A models to core/domain/models/`.

### B2 — Risk B (3 файла + secondary)

`orderkinds.py`, `orders.py`, `files.py`. Циклический rel-граф:
- `OrderKind.orders` ↔ `Order.order_kind` (`back_populates`)
- `File.orders` ↔ `Order.files` (через `OrderFile`)

Требует careful MRO при переносе + проверка `relationship()` `secondary=`
lambda сохраняет отложенное разрешение.

**Шаги:**
1. После B1 (carrier `base.py` уже на месте).
2. `git mv orderkinds.py` первым, фикс imports.
3. `git mv orders.py`, фикс `FK→orderkinds`.
4. `git mv files.py` + `OrderFile`, фикс secondary association.
5. Commit per файл: `refactor(s105-b2-d5-orderkinds)`, `refactor(s105-b2-d5-orders)`, `refactor(s105-b2-d5-files)`.

### B3 — Risk C (2 файла, complex)

`workflow_instance.py` + `workflow_event.py`. Содержат:
- `Enum(WorkflowStatus, native_enum=True, create_constraint=False)` — Alembic
  миграция `c3d4e5f6a7b8` создаёт PG type'ы.
- `FK workflow_event.workflow_id → workflow_instances.id ONDELETE CASCADE`.
- `make_versioned(...)` + plugin init в `base.py` — singleton-проблема
  при двойном импорте.

**Шаги:**
1. Сначала перенести `workflow_instance.py` (target FK).
2. Перенести `workflow_event.py` (FK source).
3. Создать Alembic-совместимую миграцию (если требуется re-create enum types).
4. Commit: `refactor(s105-b3-d5-workflow)`.

---

## 5. Risk Mitigation

| Риск | Митигация |
|------|-----------|
| Hard delete extensions imports | Shim слой (1 sprint grace) + DeprecationWarning |
| FK circular import (B2) | `configure_mappers()` в `__init__.py` после всех imports |
| Enum native_enum (B3) | Alembic `op.create_type()` / `op.drop_type()` миграция |
| `make_versioned` singleton (B3) | Lazy import в `base.py`, гарантия single load |
| CI regression | `tools/check_layers.py` + `tests/unit/infrastructure/database/` regression suite |
| Migration env.py sync | Минимальное изменение путей в `migrations/env.py:18-28` (вариант A из OPEN Q4) |

---

## 6. Rollback Plan

Каждый B1/B2/B3 commit обратим:
```bash
git revert <commit-hash>   # откат 1 batch
# Или:
git reset --hard <prev-commit>   # hard reset, если shim'ы ещё на месте
```

**Backstop:** shim'ы в `infrastructure/database/models/` сохраняют
back-compat 1 sprint. Если что-то сломается — extensions могут импортировать
из старого пути, пока shim работает (с warning).

---

## 7. Verification (scripts/verify_d5_migration_readiness.sh)

Pre-flight check перед началом миграции:
- Model count: 12 файлов в `infrastructure/database/models/`.
- Reflection: `BaseModel.metadata.tables.keys()` содержит все ожидаемые таблицы.
- Linter: 41 violation в extensions (baseline).
- No `_emit_audit` in `core/audit/facade.py` (sanity).

Post-B1 check:
- 6 файлов перенесены в `core/domain/models/`.
- 6 shim'ов в `infrastructure/database/models/`.
- Linter: 41 → ~25 violations (только B2/B3 dependents).
- `pytest tests/unit/infrastructure/database/` — pass.

---

## 8. Out of Scope

- Реальный перенос (multi-sprint) — S105+ execution.
- `rule_engine.py` isolation refactor — отдельный sprint (см. ADR-0188 Q5).
- `infrastructure/database/model_registry.py` — sync с новым местоположением
  (часть B1 шага 4).
- Alembic migration creation для native enum recreate — B3 (если требуется).
