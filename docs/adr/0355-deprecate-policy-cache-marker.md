# ADR-0355: Deprecate `policy.cache()` marker — rename to `cache_policy` (cycle 170)

* **Статус**: ACCEPTED (2026-10-20, cycle 170, пользователь Mavis)
* **Cycle**: 170
* **Связан с**: `DSL_AUDIT_CACHE_LOGGING_2026-10-20.md` §2.3
* **Затрагивает**: `src/backend/dsl/builders/policy_mixin.py`

## Контекст

Cycle 169 audit (§2.3) обнаружил **MRO collision** в `RouteBuilder.cache()`:

| MRO position | Source | Signature | Behavior |
|---|---|---|---|
| `RouteBuilder.cache` (priority) | `dsl/builders/ai_rpa/rpa.py` | `(key_fn, *, ttl=3600)` | Реальный `CacheProcessor` (Redis) |
| `PolicyMixin.cache` (overridden) | `dsl/builders/policy_mixin.py` | `(*, ttl_seconds=60, key=None, backend="redis")` | `PolicyMarkerProcessor` — **no-op marker** |

Два метода с одинаковым именем `cache`, но **разной семантикой**.

### Проблема

`policy_mixin.py::cache()` создаёт `PolicyMarkerProcessor` — marker,
который ставится в pipeline но **не реализует** cache логику:

```python
# policy_mixin.py:61-67
def cache(
    self, *, ttl_seconds: int = 60, key: str | None = None, backend: str = "redis"
) -> RouteBuilder:
    """Add cache policy (через CacheProcessor / Redis backend)."""
    return self._add_policy_processor(
        "cache", ttl_seconds=ttl_seconds, key=key, backend=backend
    )
```

Docstring обещает "через CacheProcessor / Redis backend", но реально —
это просто marker, который никак не интегрирован с cache.

**MRO collision**: при `RouteBuilder.cache(ttl_seconds=60, ...)` будет
вызван первый `cache` в MRO (обычно `PolicyMixin.cache`), что даст
no-op вместо реального cache. Пользователь думает, что cache работает,
но на самом деле ничего не происходит.

### Status

MEDIUM risk (misleading API → silent no-op cache).

## Решение

**Deprecate `PolicyMixin.cache()`** через:
1. **DeprecationWarning** при вызове.
2. **Rename** в новый метод `PolicyMixin.cache_policy()` (явное
   отличие от `RouteBuilder.cache()`).
3. **Backward-compat shim** — старый `cache()` вызывает `cache_policy()`
   с warning.

### Миграция

```python
# OLD (deprecated):
builder.policy.cache(ttl_seconds=60)

# NEW (canonical):
builder.policy.cache_policy(ttl_seconds=60)
```

### Шаги

1. `policy_mixin.py`: rename `cache()` → `cache_policy()`.
2. Добавить **deprecated shim** `cache()` который вызывает
   `cache_policy()` с `warnings.warn(DeprecationWarning)`.
3. Обновить существующие callers (если есть) на новое имя.
4. Документация: обновить `docs/dsl/index.md` и `docs/ai/index.md` —
   убрать упоминания `policy.cache()` или пометить как deprecated.

## Альтернативы

### Option B: полностью удалить marker (rejected)

`git rm` `PolicyMixin.cache()` + `cache_policy()`.

**Плюсы**: чистый API без misleading marker.

**Минусы**:
- Breaking change для пользователей, которые вызывают `policy.cache()`.
- Нет migration path для них.

**Rejected** в пользу Option A (deprecate с shim — backward-compat).

### Option C: реализовать реальный cache в `PolicyMixin.cache()` (rejected)

Интегрировать `policy_mixin.cache()` с `services.cache.UnifiedCacheFacade`.

**Плюсы**: marker становится реальным cache.

**Минусы**:
- Расширяет scope ADR-0355 (тоже можно, но отдельный ADR).
- Дублирует функциональность `RouteBuilder.cache()`.

**Rejected** для cycle 170. Может быть рассмотрено в cycle 180+ как
отдельный ADR (см. ADR-0354 followup).

## Последствия

### Позитивные

- Явный сигнал пользователю: `policy.cache()` deprecated, использовать
  `policy.cache_policy()`.
- Нет silent no-op cache — явный warning.
- Backward-compat сохранена через shim.

### Негативные

- Дублирование API (deprecated `cache()` + canonical `cache_policy()`)
  на период migration.
- После полной migration (cycle 175+) — deprecated метод можно удалить.

## Проверка после реализации

```bash
# 1. DeprecationWarning emits
uv run python -W error::DeprecationWarning -c "
from src.backend.dsl.builders.base import RouteBuilder
RouteBuilder.from_('test', source='http:GET /test').policy.cache(ttl_seconds=60)
" 2>&1 | grep -i deprecation

# 2. Новый метод работает без warning
uv run python -c "
from src.backend.dsl.builders.base import RouteBuilder
RouteBuilder.from_('test', source='http:GET /test').policy.cache_policy(ttl_seconds=60)
"

# 3. Layer check
uv run python tools/check_layers.py --strict

# 4. Существующие тесты passing
uv run pytest tests/unit/dsl/ -q
```

## Статус реализации

**Cycle 170** (этот ADR). Реализация + warning + тесты + коммит.

## Followup (cycle 175+)

- Удалить deprecated shim `policy.cache()` после полной migration
  (когда ни один caller не использует старое имя).
- Решить: реализовать ли реальный cache в `policy.cache_policy()`
  через `UnifiedCacheFacade` (см. ADR-0354 followup).