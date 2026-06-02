# T2.1 — Audit CircuitBreaker callsites (ОБНОВЛЕНО)

> **T2.1 артефакт.** Аудит 15 реализаций CB перед консолидацией.
> Цель: понять какой API реально используется → выбрать канонический.
> **Факт-чекинг 02.06.2026:** 15 файлов (не 5 как в v9), canonical уже есть.

## Все CB-файлы (15 шт, факт)

| # | Файл | Статус | Примечание |
|:-:|------|:------:|------------|
| 1 | `core/resilience/breaker.py` | **canonical** | V22.10.2 wave 1, ADR-005 |
| 2 | `core/resilience/decorators.py` | wrapper | `@circuit_breaker` decorator |
| 3 | `core/resilience/resilience_profile.py` | profile API | `BreakerPolicy` |
| 4 | `core/resilience/rpa_policy.py` | rpa-specific | — |
| 5 | `core/utils/circuit_breaker.py` | **legacy** | `interfaces.CircuitBreaker` (не canonical!) → deprecate |
| 6 | `core/utils/pybreaker_adapter.py` | **active migration** | Protocol для purgatory→pybreaker (default-OFF feature) |
| 7 | `core/config/services/resilience.py` | config | services-level CB config |
| 8 | `core/interfaces/observability.py` | interface | metrics protocol |
| 9 | `infrastructure/resilience/client_breaker.py` | **adapter** | `ClientCircuitBreaker` поверх canonical (host label, from_profile) |
| 10 | `infrastructure/resilience/redis_breaker_storage.py` | storage | Redis state |
| 11 | `infrastructure/clients/external/circuit_breakers.py` | **adapter** | pre-registered breakers поверх canonical |
| 12 | `infrastructure/logging/backends/graylog_gelf.py` | unrelated | "Breaker" в имени класса — не CB |
| 13 | `dsl/engine/processors/eip/resilience.py` | DSL wrapper | `.circuit_breaker()` EIP |
| 14 | `entrypoints/api/v1/endpoints/admin_resilience_profile.py` | admin | endpoint, не CB |
| 15 | `core/interfaces/__init__.py` | re-export | — |

**Реальных CB реализаций: 8-10** (исключая endpoints, interfaces, unrelated)

## Ревизия T2.1 (факт-чек 02.06.2026 v2)

Первоначальный audit помечал **4 legacy shim'а** для deprecation. Реальность:

| Файл | T2.1 метка | Реальность | T2.2 решение |
|------|-----------|------------|--------------|
| `infrastructure/resilience/client_breaker.py` | legacy shim | **adapter поверх canonical** (импортирует `BreakerSpec, get_breaker_registry, CircuitOpen`) | **НЕ трогаем** |
| `infrastructure/clients/external/circuit_breakers.py` | legacy shim | **adapter поверх canonical** (импортирует `Breaker, BreakerSpec, get_breaker_registry`) | **НЕ трогаем** |
| `core/utils/circuit_breaker.py` | legacy | **legacy** (импортирует `interfaces.CircuitBreaker`, не canonical) | **DEPRECATE** |
| `core/utils/pybreaker_adapter.py` | legacy | **active migration adapter** (Protocol + Factory для purgatory→pybreaker через feature flag) | **НЕ трогаем** |

**Итог T2.2 scope:** 1 файл для deprecation, не 4.

## Canonical API (по V22.10.2 wave 1, ADR-005)

```python
# core/resilience/breaker.py
from src.backend.core.resilience import CircuitBreaker, BreakerRegistry

# Async context manager
async with BreakerRegistry.get_or_create("name", spec).guard():
    await external_call()
```

**Aliases:** `CircuitBreaker == Breaker`
**Re-export:** `core/resilience/__init__.py` экспортирует `CircuitBreaker`, `BreakerSpec`, `BreakerRegistry`, `CircuitOpen`.

## Что НЕ сделано в V22.10.2 (work for S38 W2)

1. **DeprecationWarning в legacy `core/utils/circuit_breaker.py`** (только 1 файл, не 4):
   - Импортирует `interfaces.CircuitBreaker` (не canonical)
   - Требует миграции на `core.resilience.breaker.CircuitBreaker`
2. **Migration guide** в docs/ для callsite'ов, использующих legacy API
3. **Test coverage** для canonical `breaker.py` (≥85% per S38 metrics)

**Не нужно депрекейтить** (reвизия T2.1):
- `infrastructure/resilience/client_breaker.py` — adapter (уже поверх canonical)
- `infrastructure/clients/external/circuit_breakers.py` — adapter (уже поверх canonical)
- `core/utils/pybreaker_adapter.py` — active migration feature (default-OFF)

## T2.2 — Выбор стратегии

**Рекомендация:** **D2 (deprecate + re-export)** для `core/utils/circuit_breaker.py`:

```python
# core/utils/circuit_breaker.py (после deprecation)
import warnings
warnings.warn(
    "core.utils.circuit_breaker is deprecated, use core.resilience.breaker.CircuitBreaker",
    DeprecationWarning, stacklevel=2,
)

# Backwards-compat: сохраняем старый класс
from src.backend.core.interfaces import CircuitBreaker as _CircuitBreakerImpl
from src.backend.core.interfaces import CircuitBreakerConfig

__all__ = ("CircuitBreaker", "get_circuit_breaker")
# ... existing code ...
```

**Не** удаляем legacy код (V24+) — оставляем с DeprecationWarning для backwards-compat.

**Не** депрекейтим 3 адаптера — они полезны и уже поверх canonical.

## Что НЕ делаем в W2

- ❌ Не удаляем legacy shim'ы (V24+)
- ❌ Не переписываем DSL wrapper `eip/resilience.py` (он уже использует canonical)
- ❌ Не делаем breaking changes в публичном API

## Следующий шаг (T2.2)

1. Grep callsites каждого legacy файла
2. Пометить DeprecationWarning в 4 legacy shim'ах
3. re-exports для backwards-compat
4. Smoke test
5. Ревью + commit

## Открытые вопросы

- `core/utils/circuit_breaker.py` — уже помечен как "исторический" в `__init__.py`. Можно не депрекейтить явно (уже deprecated фактически)?
- `core/utils/pybreaker_adapter.py` — реально используется? Проверить callsite.
- `dsl/engine/processors/eip/resilience.py` — wrapper над canonical, не нужно депрекейтить (он OK).
- `core/config/services/resilience.py` — это config, не CB. Не трогаем.
