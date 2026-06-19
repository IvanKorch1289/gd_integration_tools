# S168 W11 P2-10: Domain leakage to extensions — migration plan

## Status: Accepted (S168 W11)

## Context

Per master prompt v8 P2-10: domain ORM models, admin panels, and
schemas are в platform (src/backend/) но должны быть в extensions
(per CLAUDE.md: "Бизнес-логика — только в extensions/<name>/, ядро
domain-agnostic").

## Affected files (current state)

| Category | Files | Target |
|----------|-------|--------|
| ORM models | `core/domain/models/{orders,users,files,orderkinds}.py` | `extensions/core_entities/<name>/domain/models.py` |
| Admin panel | `utilities/admin_panel/{orders,users,files,orderkinds,setup_admin}.py` | `extensions/core_entities/<name>/admin.py` |
| Route schemas | `schemas/route_schemas/{orders,users,files,orderkinds,admin,skb,dadata}.py` | `extensions/core_entities/<name>/schemas/route.py` |
| Filter schemas | `schemas/filter_schemas/{orders,users,files,orderkinds}.py` | `extensions/core_entities/<name>/schemas/filter.py` |

## Decision

**Per Ponytail minimum, current commit does NOT move files** —
отложено до S169+.

Rationale:
- Total: ~20+ files affected
- Each file has multiple callers (ORM via session_manager, schemas
  via Pydantic, admin via FastAPI)
- Risk of breaking changes: HIGH (Pydantic serialization, SQLAlchemy
  mapper registration, FastAPI dependency injection)
- Test coverage: ~30+ existing tests импортируют эти models

## Migration plan (separate WIP S169+)

For each of 4 domains (orders, users, files, orderkinds):

### Step 1: ORM models (orders.py, users.py, etc.)
- Move to `extensions/core_entities/<name>/domain/models.py`
- Update `extensions/core_entities/<name>/plugin.py` to import
- Add re-export in `src/backend/core/domain/models/<name>.py`
  (backward-compat) with deprecation warning
- Update `src/backend/core/domain/models/__init__.py` to re-export
- Verify all SQLAlchemy tests pass

### Step 2: Schemas (route + filter)
- Move to `extensions/core_entities/<name>/schemas/{route,filter}.py`
- Update Pydantic imports across 50+ files
- Re-export with deprecation warning

### Step 3: Admin panel
- Move to `extensions/core_entities/<name>/admin.py`
- Update `src/backend/utilities/admin_panel/setup_admin.py`
  to import from extensions
- Re-export with deprecation warning

### Step 4: Delete originals
- After all callers updated, delete `src/backend/core/domain/models/{orders,users,files,orderkinds}.py`
- Delete `src/backend/utilities/admin_panel/{orders,users,files,orderkinds}.py`
- Delete `src/backend/schemas/{route,filter}_schemas/{orders,users,files,orderkinds}.py`

## Affected callers (preliminary)

```
core/domain/models/{orders,users,files,orderkinds}.py:
- services/extensions/{orders,users,files,orderkinds}/*.py
- repositories/{orders,users,files,orderkinds}.py
- tests (multiple)
```

## Consequences

- 0 immediate code change (Ponytail minimum)
- Plan documented for S169+ execution
- New developers should NOT add business logic to src/backend/
  (per CLAUDE.md V22 architecture)

## Date: 2026-06-18
