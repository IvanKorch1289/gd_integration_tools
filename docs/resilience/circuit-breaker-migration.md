# Circuit Breaker Migration Guide (S38)

> **Audience:** разработчики, мигрирующие callsite'ы с deprecated
> `core.utils.circuit_breaker` на canonical `core.resilience.breaker.CircuitBreaker`.
> **Status:** v1 (S38 W2 T2.3) | **Removal:** V24+

## TL;DR

| Аспект | Старый (deprecated) | Canonical |
|--------|---------------------|-----------|
| **Импорт** | `from core.utils.circuit_breaker import CircuitBreaker` | `from core.resilience.breaker import CircuitBreaker, BreakerRegistry` |
| **API** | `await cb.check_state(...)` (raise on open) | `async with BreakerRegistry.get_or_create("name", spec).guard():` |
| **State** | `is_open() -> bool` (sync) | `breaker.state` (property) |
| **Records** | `cb.record_success()` / `cb.record_failure()` | `Breaker` (context manager) — auto |
| **Метрики** | `interfaces.CircuitBreaker` protocol | `CircuitBreakerMetricsRecorder` (V22.10.2) |
| **Backwards-compat** | До V24+ | — |
| **Default** | default-OFF features | default-OFF (Wave 6.1) |

## Зачем мигрировать

1. **Canonical** — V22.10.2 wave 1 + ADR-005. Single source of truth.
2. **Async context manager** — `guard()` упрощает логику (no manual check_state/record).
3. **Per-host метрики** — `BreakerRegistry` поддерживает `host` label.
4. **State machine унифицирован** — `closed` / `open` / `half_open` (нормализованные).

## До/После

### До (legacy)

```python
from src.backend.core.utils.circuit_breaker import CircuitBreaker

cb = CircuitBreaker(reset_timeout=30, name="redis")
try:
    await cb.check_state(
        max_failures=5,
        exception_class=ConnectionError,
        error_message="Redis circuit open",
    )
except ConnectionError:
    return None  # fail-fast
result = await redis.get(key)
cb.record_success()
return result
```

### После (canonical)

```python
from src.backend.core.resilience.breaker import BreakerRegistry, BreakerSpec

registry = BreakerRegistry.get_or_create("redis", BreakerSpec(
    failure_threshold=5,
    recovery_timeout=30.0,
))
try:
    async with registry.guard():
        return await redis.get(key)
except CircuitOpen:
    return None  # breaker raised
```

**Изменения:**
- `reset_timeout` → `recovery_timeout` (float seconds)
- `max_failures` → `failure_threshold`
- `check_state` (raise) → `guard()` (async context manager, raises `CircuitOpen`)
- `name` теперь атрибут registry, не cb
- Нет `record_success/failure` — context manager делает auto

## Coexistence (S38 → V24)

- ✅ Старый API **работает** с `DeprecationWarning` при импорте
- ✅ Можно мигрировать постепенно (PR за PR)
- ✅ В одном проекте можно иметь оба API (warnings покажут legacy)
- ❌ Не рекомендуется смешивать в одном модуле (для ясности)

## План миграции для существующих callsite'ов

### Шаг 1: Найти callsite'ы

```bash
grep -rln 'from src.backend.core.utils.circuit_breaker' src/
```

Ожидаемые файлы: `core/utils/circuit_breaker.py` сам + 1-2 callsite (http.py, smtp.py и т.п.).

### Шаг 2: Per-callsite migration

Для каждого файла:
1. Заменить импорт на canonical
2. Переписать `check_state` блок на `async with registry.guard()`
3. Убрать `record_success/failure` (auto)
4. Обновить exception handling (`ConnectionError` → `CircuitOpen`)

### Шаг 3: Тестирование

- Smoke test: `from core.resilience.breaker import CircuitBreaker` (no warning)
- Integration test: `async with registry.guard(): ...` работает в expected scenarios
- Deprecated path test: импорт `core.utils.circuit_raiser` всё ещё работает + warning

### Шаг 4: Удаление (V24+)

После того как все callsite'ы мигрированы:
1. Удалить `core/utils/circuit_breaker.py`
2. Удалить `__pycache__` артефакты
3. Update any `__init__.py` re-exports

## Edge cases

| Случай | Поведение |
|--------|-----------|
| `pybreaker_adapter.py` (миграционный feature) | Не зависит от legacy, не трогаем |
| `dsl/engine/processors/eip/resilience.py` | Использует canonical, OK |
| `infrastructure/resilience/client_breaker.py` | Adapter поверх canonical, OK |
| `infrastructure/clients/external/circuit_breakers.py` | Adapter поверх canonical, OK |

## Тесты (S38 W2 T2.3)

Существующие тесты:
- `tests/webhook/test_resilience.py` — webhook integration
- `tests/unit/core/resilience/test_resilience_profile.py` — BreakerPolicy API

**Что нужно добавить** (отложено в S38 backlog):
- `tests/unit/core/resilience/test_breaker.py` — canonical coverage ≥85%
- `tests/unit/core/utils/test_circuit_breaker_deprecation.py` — DeprecationWarning test

## См. также

- `.hermes/plans/S38_W2_P23_CB_audit.md` — полный audit CB
- `.hermes/plans/S38_V23_PLAN.md` — S38 план (W2 раздел)
- ADR-005 (Single source of truth для resilience)
- V22.10.2 wave 1 — V22 release notes
