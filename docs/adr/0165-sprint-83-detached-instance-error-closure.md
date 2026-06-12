# ADR-0165: Sprint 83 — DetachedInstanceError Closure (V2 P0 N1)

**Status**: Accepted
**Date**: 2026-06-12
**Sprint**: S83 (Data Corruption Fix)
**Author**: Ivan (autonomous cycle)

## Context

FINAL_REPORT_V2 N1: `SQLAlchemyRepository.update()` (base/sqlalchemy.py:360,380) возвращает
SQLAlchemy object после `session.refresh()`. После выхода из
`@main_session_manager.connection()` session closed, объект detached,
доступ к `obj.field` = `DetachedInstanceError` → **data corruption**
при cascading reads/writes в caller code.

Pre-existing в `delete()`: возвращал `None` → audit log терял ID
удалённого объекта.

## Decision

### W1: `expire_on_commit=False` (REVERTED в W3)

Первая попытка: `session.expire_on_commit = False` на время refresh.
**BROKEN**: `AsyncSession` не имеет `expire_on_commit` attribute —
это `Session` (sync), нужен `session.sync_session.expire_on_commit`.

### W3: `attribute_names=...` (FINAL fix)

```python
mapper = inspect(obj.__class__)
all_column_names = [c.key for c in mapper.columns]
await session.refresh(instance=obj, attribute_names=all_column_names)
```

`refresh()` с конкретным списком attrs **не expire'ит остальные**:
- attrs из списка → reloaded из DB
- attrs не из списка → остаются loaded (не expired)
- после commit() attrs остаются accessible, объект usable до GC
- безопаснее чем `expire_on_commit=False` (глобально) — не ломает
  concurrent sessions

### W2: `delete()` returns ID

```python
async def delete(self, session, key, value) -> int | None:
    result = await session.execute(
        delete(self.model).where(...).returning(self.model.id)
    )
    await session.flush()
    row = result.scalar_one_or_none()
    return int(row) if row is not None else None
```

Caller получает ID для audit logging. Проверено: ни один caller в
`src/` не использует return value `SQLAlchemyRepository.delete()`.

## Consequences

### Positive
- V2 P0 N1 (data corruption) CLOSED
- 5/5 regression tests pass + 2/2 idempotency tests
- `delete()` теперь возвращает ID → audit log может логировать что удалено

### Negative
- `attribute_names=all_column_names` re-fetch'ит ВСЕ columns при refresh
  (был partial refresh в некоторых кейсах) — minor perf overhead
- 0 callers сломанных (backward-compatible signal change для `delete()`)

## Tests Added

- `test_update_returned_object_attrs_accessible` — регрессия N1
- `test_update_returned_object_usable_in_caller` — caller-side use
- `test_delete_returns_object_id` — W2
- `test_delete_returns_none_when_not_found` — W2
- `test_update_does_not_affect_other_sessions` — concurrent safety
- `test_update_idempotent_on_repeated_calls` — W4
- `test_delete_idempotent` — W4

**Total: 7 NEW tests, 7/7 pass.**

## Files Changed

- `src/backend/infrastructure/repositories/base/sqlalchemy.py` (W1, W2, W3)
- `tests/unit/infrastructure/repositories/test_base_repository.py` (W3, W4)
- `CHANGELOG.md` (W5)
- `.shared/context/TECH_DEBT.md` (W5)

## Related ADRs

- ADR-0144 (S64 multi-instance safety)
- ADR-0154 (S72 outbox per-row claim)

## Outcome

- **V2 P0 N1 CLOSED** — DetachedInstanceError fix shipped
- 4 commits, 7 NEW tests, 1 backward-compat signal change
- Files affected: только `SQLAlchemyRepository` (и все 30+ subclass repositories)
