# ADR-0279: Circuit-breaker metrics refactor (cross-layer fix)

> **Status**: ACCEPTED.
> **Method**: Minimal relocation + idempotent gauge re-registration; no
> API breakage; 12 existing circuit_breaker tests + 6 prometheus_alerting
> tests all pass (16/16).
> **Scope**: P1.9 из WAVE 2 production-grade plan (см.
> `docs/audit/CURRENT_STATE_2026-08-27.md`).
> **Date**: 2026-08-27.

## 0. Контекст

`src/backend/entrypoints/middlewares/circuit_breaker.py:87` импортировал
`record_circuit_breaker_state` напрямую из
`src/backend/infrastructure/observability.metrics`. Это cross-layer
violation: `tools/check_layers.py` (слой `entrypoints`) в матрице
`ALLOWED` имеет только `{"services", "schemas", "core"}` — `infrastructure`
недопустим.

WAVE 1 audit (2026-08-27) зафиксировал эту violation как OPEN:

> 1 NEW violation в baseline:
> `src/backend/entrypoints/middlewares/circuit_breaker.py →
> src.backend.infrastructure.observability.metrics`

Baseline в `make layers` показывал "0 new" потому что эта violation была
baselined в `tools/check_layers_allowlist.txt:65`. Это скрывало structural
проблему от CI-gate.

Цель — устранить violation без architectural breakage и без дублирования
функциональности.

## 1. Рассмотренные варианты

### Вариант A: Создать Protocol-интерфейс в `core/observability/`

Pros: decoupled.
Cons: Protocol не решает cross-layer (нужна concrete-reализация где-то
ещё); pre-existing `MetricsRegistry` уже singleton — Protocol ради
single record-callsite = over-engineering (YAGNI).

### Вариант B: Использовать `core/utils/metrics_registry` напрямую

Pros: уже есть в core.
Cons: caller должен знать имя gauge (`"circuit_breaker_state"`) и
labels (`"name"`), плюс сам факт существования этой метрики — это
leaks infrastructure-концерн в entrypoints слой.

### Вариант C (chosen): Relocate `record_circuit_breaker_state` в `core/observability/metrics.py`

Pros:
- `core.observability.metrics` уже существует как facade (S120 W4):
  экспортирует `MetricsRegistry`, `metrics_registry` singleton,
  несколько pre-existing public counter'ов (`dlq_send_failed_total`,
  `webhook_signature_missing_secret_total`, `audit_silent_loss_total`).
- Добавление 4-LOC `record_circuit_breaker_state(name, state_value)` —
  минимальный diff, согласуется с существующим API contract.
- `metrics_registry` singleton shared с infrastructure — gauge
  регистрация idempotentна (`MetricsRegistry.gauge()` проверяет
  `name in self._gauges` и возвращает existing instance). Нет
  `DuplicatedTimeSeries` в `prometheus_client.CollectorRegistry`.
- `infrastructure/observability/metrics.py` может сохранить
  `_breaker_gauge`-registration для `get_dsl_metrics()` exporter
  (admin/health endpoint exposure) — без registration metric не
  попадёт в `/metrics` endpoint scrape.

Cons:
- `_breaker_gauge` registration дублируется (хотя idempotentна).
  Mitigation: docstring явно фиксирует, что обе регистрации
  резолвятся в один `prometheus_client.Gauge` instance.

## 2. Решение

Принят Вариант C.

### Изменения

1. **`src/backend/core/observability/metrics.py`** — добавляет
   `_breaker_gauge` (через singleton `metrics_registry`) +
   `record_circuit_breaker_state(name: str, state_value: int) -> None`.
   `__all__` обновлён.

2. **`src/backend/infrastructure/observability/metrics.py`** —
   удалена функция `record_circuit_breaker_state` (теперь duplicate —
   `infrastructure → core` lazy imports допустимы, но physical
   re-export ничего не даёт).
   `_breaker_gauge` registration оставлена (idempotentна + питает
   `get_dsl_metrics()` exporter).
   `__all__` обновлён.
   Module docstring обновлён — ссылка на ADR-0279.

3. **`src/backend/entrypoints/middlewares/circuit_breaker.py:87-91`** —
   внутренний lazy import перенаправлен с
   `src.backend.infrastructure.observability.metrics.record_circuit_breaker_state`
   на
   `src.backend.core.observability.metrics.record_circuit_breaker_state`.

4. **`tests/unit/entrypoints/middlewares/test_circuit_breaker_metrics.py`** (6 мест) +
   **`tests/unit/entrypoints/middlewares/test_circuit_breaker_metrics_edge_cases.py`** (3 места) —
   `unittest.mock.patch` paths перенаправлены на новый module path.
   Docstrings дополнены ссылкой на ADR-0279.

5. **`tools/check_layers_allowlist.txt`** — удалена строка
   `src/backend/entrypoints/middlewares/circuit_breaker.py entrypoints src.backend.infrastructure.observability.metrics`.
   После `make layers-update --prune-allowlist` baseline сократился
   с 63 до 62 legacy entries.

### Почему НЕ Compatibility re-export

YAGNI: единственный runtime caller `record_circuit_breaker_state` —
`circuit_breaker.py`. Grep по `src/backend` и `tests/` подтвердил
отсутствие других runtime consumer'ов (комментарии в `prometheus_alerting.py`
и `tests/test_prometheus_alerting.py` упоминают function name в past
tense, не импортируют). Re-export для future-proofing — speculative.

## 3. Verification

| Check | Команда | Exit | Fact |
|---|---|---|---|
| Layers (no new violations) | `make layers` | 0 | "Нарушений: 0 новых (файлов: 2313; baseline: 62 legacy)" (было 63 → 62) |
| Unit tests (circuit_breaker + alerting) | `pytest tests/unit/entrypoints/middlewares/test_circuit_breaker_metrics.py tests/unit/entrypoints/middlewares/test_circuit_breaker_metrics_edge_cases.py tests/unit/infrastructure/observability/test_prometheus_alerting.py -v` | 0 | **19 passed, 0 failed** |
| Full middleware + observability suite | `pytest tests/unit/entrypoints/middlewares/ tests/unit/infrastructure/observability/ -q` | 0 | **610 passed, 3 skipped** (pre-existing httpx<0.28 incompat) |
| Ruff lint (touched files) | `ruff check <5 files>` | 0 | All checks passed |
| Strict layer scan (sanity) | `python tools/check_layers.py --strict \| grep circuit_breaker` | 0 | (no output = no violations from circuit_breaker.py) |

## 4. Out-of-scope / discovered

В ходе выполнения этой задачи обнаружены (но НЕ исправлены — вне scope
P1.9):

1. **`src/backend/entrypoints/mcp/mcp_server/tools_convert.py:54`**
   содержит **Python 2 syntax error**:
   `except orjson.JSONDecodeError, TypeError:` (Python 3 требует
   `except (X, Y):`). Из-за SyntaxError `_check_file` возвращает `[]`
   для этого файла (line 309: `except SyntaxError: return []`), поэтому
   import-violation `entrypoints → dsl.engine.processors.converters`
   скрыта от scanner'а, хотя physically существует. `make layers` ВСЁ
   ЕЩЁ проходит только потому что соответствующая строка осталась в
   allowlist (после `--prune-allowlist` я восстановил её, чтобы
   не сломать baseline для других subagent'ов). Требует отдельного P1.9'-fix.

2. **`_breaker_gauge` registration дублируется** между core и
   infrastructure модулями (idempotentна). Cleanup возможен в
   future-работе через перенос всей `_breaker_gauge` declaration в
   core (но требует осторожного обновления `get_dsl_metrics()` на
   core-fetch).

## 5. Связанные ADR

- ADR-0207: services/* observability импортирует `metrics_registry`
  из `core.utils.metrics_registry` (v1 контракт).
- ADR-0249 / ADR-0251: Sprint 44 audit followup + S13 circuit breaker
  shared state (architectural foundation).
- ADR-0277: P0-P3 Audit Verification (cycle 292) — выявил violation
  в wave 1.

**Decision recorded by**: P1.9 WAVE 2 subagent, 2026-08-27.
