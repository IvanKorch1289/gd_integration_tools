# ADR-0305 — Circuit Breaker consolidation поверх purgatory

* Статус: **Draft** (2026-09-23).
* Связано с: W1 (P0-1) плана MINIMAX; ADR-0084 (библиотеки > кастом).
* Память: [[feedback_wave_xx]].

## Контекст

**Проблема**: В проекте сосуществуют **3 модуля** circuit breaker с overlapping
ответственностями, что нарушает архитектурный принцип «один способ сделать X»
(см. новый objective, раздел 4).

| Модуль | LOC | Ответственность |
|---|---|---|
| `core/resilience/breaker.py` | 336 | **Canonical** (Sprint 1 V16 Single-Entry): pure purgatory wrapper. Exports: `Breaker`, `BreakerLike`, `CircuitOpen`, `BreakerRegistry`, `get_breaker_registry`, `BreakerSpec`, `BreakerState`. |
| `core/resilience/circuit_breaker.py` | 252 | **Facade** (S172 M2.3 → S173 M2.4): re-export + 2 специализированных CB поверх purgatory: `SlidingWindowBreaker` (per-route time-window semantics) + `ReplicaFailoverBreaker` (read-replica failover). Также объявляет `BreakerLike` Protocol для RPA. |
| `entrypoints/middlewares/circuit_breaker.py` | 435 | **ASGI Middleware**: per-route CB state, route-based policies, metric recording. Imports из обоих файлов выше — циклическая зависимость. |
| `core/resilience/breaker_policy_adapter.py` | 180 | **Bridge adapter** (S13 Phase 2a + S52 W1 CORRECTED): bridges `CircuitBreakerMiddleware` legacy API → canonical `BreakerRegistry`. **Migration is feature-flag-controlled** (see below). |

Итого долг:
- **~687 LOC** (252 + 435) на "не-canonical" CB code.
- **1 циклическая зависимость** (`core/resilience/circuit_breaker ↔ entrypoints/middlewares/circuit_breaker`).
- **Тесты** (10 файлов, ~70 passing, 4 pre-existing failures в `test_smtp_canonical_breaker.py`):
  - `tests/unit/entrypoints/middlewares/test_circuit_breaker.py`, `test_circuit_breaker_sliding.py`
  - `tests/unit/core/resilience/test_circuit_breaker_facade.py`, `test_unified_breaker.py`,
    `test_breaker_policy_adapter.py`, `test_breaker_policy_adapter_exception.py`,
    `test_breaker_registry_redis.py`
  - `tests/unit/infrastructure/test_connector_breaker.py`,
    `tests/unit/infrastructure/clients/transport/test_smtp_canonical_breaker.py`,
    `test_http_no_circuit_breaker.py`

**Callers (audit 2026-09-23)**:
- `src/backend/infrastructure/database/smart_session_manager.py` — импортирует CB.
- `src/backend/core/observability/metrics.py` — импортирует middleware CB.
- `src/backend/core/resilience/breaker_policy_adapter.py` — re-export middleware.
- `src/backend/entrypoints/middlewares/setup_middlewares.py` — регистрирует middleware.

## **MAJOR FINDING**: CB consolidation уже **in progress** (Phase A+)

**Re-audit 2026-09-23**: Существует feature-flag-controlled progressive migration,
начатый в S13 Phase 2a (cycle 273, ADR-0269, corrected in S52 W1/cycle 285).

**Текущее состояние**:
- Feature flag: `circuit_breaker_use_registry` в `core/config/features/resilience.py`
  - `default=False` — gradual rollout per ADR-0268 §1 Phase 2b
  - `True` → middleware использует `BreakerPolicyAdapter` → `BreakerRegistry` → canonical
  - `False` → middleware держит свой `_legacy_states` dict (single-process)
- `BreakerPolicyAdapter` (180 LOC, 43/43 tests passing) — корректный bridge
  - API: `get_state`, `record_failure`, `record_success`, `should_allow`
  - S52 W1 (cycle 285) CORRECTED: правильно использует WRAPPER API (не raw purgatory)
- 10 тестов-файлов для CB логики:
  - `test_breaker_policy_adapter.py` ✅ 24 passed
  - `test_breaker_policy_adapter_exception.py` ✅ passed
  - `test_breaker_registry_redis.py` ✅ passed
  - `test_circuit_breaker_facade.py` ✅ passed
  - `test_unified_breaker.py` ✅ passed
  - `test_circuit_breaker.py`, `test_circuit_breaker_sliding.py` ✅ regression
  - `test_smtp_canonical_breaker.py` ⚠️ 2 pre-existing failures (не связано)

**Architectural verdict (REVISED)**: НЕ удалять дубли.
Реальная W1 стратегия:

1. **Rollout completion**: включить `circuit_breaker_use_registry=true` для всех путей.
2. **Verify**: full e2e + cURL проверка работы через adapter.
3. **Cleanup (после 100% rollout)**: удалить legacy `_legacy_states` path в middleware.
4. **Extract specialized**: `SlidingWindowBreaker` и `ReplicaFailoverBreaker` в отдельные модули.
5. **Delete facade** (когда extracted).

**Migration уже in-flight** — нужен мониторинг rollout, не пионерская работа.
- `src/backend/infrastructure/database/smart_session_manager.py` — импортирует CB.
- `src/backend/core/observability/metrics.py` — импортирует middleware CB.
- `src/backend/core/resilience/breaker_policy_adapter.py` — re-export middleware.
- `src/backend/entrypoints/middlewares/setup_middlewares.py` — регистрирует middleware.

**Baseline**: см. `docs/audit/MINIMAX_BASELINE.md`.

## Решение

**W1 P0-1 — структурированная консолидация на purgatory-обёртке** в 3 фазы.

### Архитектурный verdict (уточнённый после анализа)

**Не всё "duplicate" — есть нюансы ролей:**
- `breaker.py` — **PURE** purgatory wrapper (low-level API).
- `circuit_breaker.py` — **FACADE** + 2 специализированных CB (sliding-window,
  replica failover) — non-trivial logic beyond re-export.
- `middleware/circuit_breaker.py` — **ASGI INTEGRATION** (per-route state, metrics).

**Стратегия**: НЕ удалять дубли слепо. Вместо:
1. **Phase A**: оставить canonical как low-level, facade/middleware остаются
   поверх.
2. **Phase B**: документировать "1 canonical entry point per concern":
   - "Breaker instance" → `breaker.py`
   - "Specialized breakers (sliding/failover)" → `circuit_breaker.py` re-org.
   - "ASGI middleware integration" → `middleware/circuit_breaker.py`.
3. **Phase C**: extract `SlidingWindowBreaker` и `ReplicaFailoverBreaker` в отдельные
   модули (`core/resilience/sliding_window_breaker.py`,
   `core/resilience/replica_failover_breaker.py`); facade → пустой re-export.
4. **Phase D**: middleware split — `CircuitBreakerMiddleware` в свой модуль,
   адаптер к canonical `Breaker` (через `BreakerRegistry`).

### DoD (минимальный для W1 atomic commit)

- [ ] Phase A done: ADR-0305 accepted; facade file annotation обновлён.
- [ ] Phase C started: at least `SlidingWindowBreaker` extracted в собственный модуль.
- [ ] Тесты существующие проходят зелёными (`pytest tests/unit/.../test_circuit_breaker*`, `test_breaker*`).
- [ ] `make ci` зелёный (lint + type + test + readiness).
- [ ] CHANGELOG.md запись для W1 P0-1.
- [ ] `git commit` атомарный.

**Wave НЕ закрыта** пока не выполнены все условия.

## Альтернативы (отвергнуто)

1. **Просто удалить дубли слепо** — отвергнуто: facade содержит non-trivial
   logic (SlidingWindowBreaker, ReplicaFailoverBreaker), это не copy-paste.
2. **Перейти на resilience4j** — отвергнуто: purgatory уже в deps + интегрирован,
   миграция на resilience4j не даёт migration bonus в обозримом будущем.
3. **Объединить всё в один файл** — отвергнуто: cyclic dep fix лучше через
   split + canonical, чем mega-module.
4. **Удалить без shim** — отвергнуто: ~13 tests используют публичные имена.

## Verification

```bash
# Phase A (до изменений)
make lint && make type-check && make ci

# После Phase B/C/D
pytest tests/unit/entrypoints/middlewares/test_circuit_breaker*.py \
       tests/unit/core/resilience/test_circuit_breaker*.py \
       tests/unit/core/resilience/test_unified_breaker.py \
       tests/unit/core/resilience/test_breaker_policy_adapter*.py \
       tests/unit/core/resilience/test_breaker_registry_redis.py \
       tests/unit/infrastructure/test_connector_breaker.py -q

# cURL smoke (если middleware используется в HTTP пути)
curl -sf http://localhost:8000/api/v1/tech/check-all-services | jq .

# Метрики (если есть)
curl -sf http://localhost:8000/metrics | grep -i circuit_breaker
```

## Consequences

### Positive

- **Циклическая зависимость** устранена (split по concerns).
- **Явные concern boundaries** (pure / specialized / middleware).
- **~687 LOC** потенциально консолидируемы (если facade станет empty re-export).
- **Purgatory migration** применяется через single canonical entry.

### Negative

- Multi-phase migration: 4 phases × atomic commits = 4+ PRs.
- SlidingWindowBreaker / ReplicaFailoverBreaker имеют non-trivial call graphs;
  миграция требует focused tests для каждого.
- Deprecation warnings шум (PEP 702).

## Связи с другими ADR

- **ADR-0084** — библиотеки > кастомный код (базовый принцип).
- **ADR-0300** — out-of-scope implementation plan (если consolidation выходит за scope).
- Потенциальный follow-up ADR для Rate Limiter (W1 P0-2, отдельный).

## Open Questions (требуют дополнительной проверки)

1. `BreakerLike` Protocol — где используется вне breaker? (smart_session_manager.py подтверждён, ещё?)
2. Что делает `breaker_policy_adapter.py`? (ещё не смотрел — отдельный audit)
3. Есть ли API endpoint для управления breakers? (HTTP? gRPC?)
4. Какие метрики пишутся в разные форматы?

## Wave Execution Plan (W1 — поэтапно)

### Phase A — ADR + audit (этот turn)
- ✅ Создан ADR-0305.
- ✅ Создан `docs/audit/MINIMAX_BASELINE.md`.
- ⏳ Pending: проверить `breaker_policy_adapter.py`, `BreakerLike` usages.

### Phase B — facade annotation update
- Обновить docstring в `circuit_breaker.py` чтобы явно объявить его как facade.
- CHANGELOG.md запись: "W1 P0-1 Phase B".

### Phase C — extract specialized breakers
- Создать `core/resilience/sliding_window_breaker.py`.
- Создать `core/resilience/replica_failover_breaker.py`.
- `circuit_breaker.py` → re-export из новых модулей.
- Тесты существующие должны проходить (public API preserved).
- CHANGELOG.md: "W1 P0-1 Phase C".

### Phase D — middleware split
- Извлечь `CircuitBreakerMiddleware` в `entrypoints/middlewares/circuit_breaker_middleware.py`.
- Использовать canonical `Breaker` API через `BreakerRegistry`.
- Shim re-export в старом файле с deprecation warning.
- Тесты focused.
- CHANGELOG.md: "W1 P0-1 Phase D — full completion".

---

*Drafted 2026-09-23. Recon baseline: `docs/audit/MINIMAX_BASELINE.md`.*
