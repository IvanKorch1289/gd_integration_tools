# ADR-0088 — EIP 10/10 Coverage: TransactionalClient + ProcessManager (S63 W3.0)

**Status:** Accepted
**Date:** 2026-06-08
**Authors:** K3
**Sources:** роевой аудит 2026-06-08 (EIP coverage gap), [eip/transactional.py](../../../src/backend/dsl/engine/processors/eip/transactional.py)
**Supersedes:** — (additive, не заменяет существующее)
**See also:** ADR-0087 (ClaimCheck dedup, sibling wave), [SagaProcessor](../../../src/backend/dsl/engine/processors/control_flow.py) (parent для ProcessManager)

## Context

Роевой аудит 2026-06-08 проверил покрытие **10 канонических Apache Camel EIP
паттернов** в проекте. До S63 W3.0 — 8/10 (2 missing):

| # | Pattern | Status (pre-W3) | Реализация |
|---|---------|-----------------|------------|
| 1 | Aggregator | ✓ | eip/flow_control.py |
| 2 | Splitter | ✓ | eip/transformation.py |
| 3 | Content-Based Router | ✓ | eip/filter_router_sampling.py |
| 4 | Message Filter | ✓ | engine/processors/core.py (deduped S55) |
| 5 | Recipient List | ✓ | eip/routing.py + builders/eip/content_mixin.py |
| 6 | Dead Letter | ✓ | eip/resilience.py |
| 7 | Idempotent Receiver | ✓ | eip/idempotency.py |
| 8 | Claim Check | ✓ (post-W2.1) | eip/transformation.py |
| 9 | **Transactional Client** | ✗ MISSING | — |
| 10 | **Process Manager** | ✗ MISSING | Saga-alтернатива есть, но не сам паттерн |

**Проблема отсутствия Transactional Client:**

* Нет exactly-once / at-least-once гарантий для action + side-effect.
* OutboxDispatcher (S21 K2) — background polling; не покрывает synchronous
  в-execution-flow enqueue.
* Extensions, нуждающиеся в transactional semantics, должны сами писать
  custom outbox-логику (риск inconsistency + vendor lock-in).

**Проблема отсутствия Process Manager:**

* Saga (SagaProcessor в control_flow.py:530) покрывает forward/compensate,
  но **не** long-running orchestration с state-persistence.
* WorkflowBuilder (workflow/builder.py:493) + SagaBuilder — для workflow-level,
  не для inline DSL processor в route.
* Temporal backend (LiteTemporalBackend) — heavy, требует workflow setup.

**Принципы** (CLAUDE.md, sprint rules):

* "минимизация кастомного кода" — переиспользовать готовые `OutboxBackend`,
  `OutboxEvent`, `SagaProcessor` вместо writing from scratch.
* "разделение ядра от роутов/расширениц" — facade в `engine/processors/eip/`
  (core layer).
* "DSL покрытие ядра" — extensions могут использовать `.transactional_client()`
  и `.process_manager()` через RouteBuilder fluent API.

## Decision

**S63 W3.0: добавить 2 EIP-фасада в `engine/processors/eip/transactional.py` —
0 production-логики дублируется.**

### 1. TransactionalClientProcessor

```python
class TransactionalClientProcessor(BaseProcessor):
    """Camel Transactional Client EIP — outbox pattern."""

    def __init__(
        self,
        *,
        action: Callable[[Exchange], Awaitable[Any]],
        outbox_backend: Callable[[], OutboxBackend],
        event_factory: Callable[[Exchange, Any], OutboxEvent],
    ) -> None: ...

    async def process(self, exchange, context):
        # 1. Run action (если fails → no enqueue)
        # 2. Build event через factory
        # 3. Enqueue в outbox (если fails → exchange.fail)
```

**Семантика:**

* Action выполняется **до** enqueue (если action упал — НЕ enqueue).
* Enqueue выполняется через готовый `OutboxBackend.enqueue` (S5 K2 уже готов).
* `OutboxEvent` (Pydantic v2, `extra="forbid"`) — гарантированный schema.
* Exactly-once требует DB transaction wrapping (документировано в module docstring).

**Reuse:**
* `OutboxBackend` Protocol из `core/messaging/outbox.py` (S5 K2).
* `OutboxEvent` Pydantic model (там же).
* `handle_processor_error` decorator из `engine/processors/base.py`.

### 2. ProcessManagerProcessor

```python
class ProcessManagerProcessor(SagaProcessor):
    """Camel Process Manager EIP — Saga + опциональный persist_state."""

    def __init__(
        self,
        steps: list[SagaStep],
        *,
        persist_state: bool = False,
        saga_state_store: Callable[[], Any] | None = None,
    ) -> None: ...
```

**Семантика:**

* **Subclass** `SagaProcessor` — inherits 100% поведения (forward+compensate).
* При `persist_state=False` — behavior идентичен SagaProcessor.
* При `persist_state=True` — saga_state_store factory обязан быть
  передан (для future S63+ W integration с WorkflowState SQLAlchemy).
* Reuse: `SagaStep` dataclass, `_emit_saga_audit` helper.

**Reuse:**
* `SagaProcessor` (control_flow.py:530) — parent class.
* `SagaStep` (там же).
* Опционально `WorkflowState` SQLAlchemy (S21 K3 W3) — для persist_state.

## Consequences

### Positive
* **EIP coverage 10/10** — все canonical Apache Camel patterns реализованы.
* **0 production-логики дублируется** — только thin facades.
* **Минимальный LOC**: ~190 implementation + ~340 tests = ~530 LOC.
* **Расширяемость** — extensions могут вызывать `.transactional_client(...)`
  и `.process_manager(...)` через RouteBuilder.

### Negative
* **LSP false positive** — Pyright не находит `src.backend.*` imports
  (pre-existing, не блокирует).
* **DB transaction требует user action** — TransactionalClient гарантирует
  только ordering, не atomicity. Full EoS — на стороне пользователя.
* **ProcessManager ≠ full Process Manager EIP** — это facade для inline
  orchestration, не external state-machine (для full PM → WorkflowBuilder +
  Temporal backend).

### Neutral
* **EIP coverage dashboard** (S63 W4) покажет 10/10 green status.
* **Saga/SagaLRA дубли** (engine/saga_lra.py + processors/saga_lra_processor.py)
  — вне scope W3.0, может быть в S63+ future wave.

## Verification

```bash
# Tests
pytest tests/unit/dsl/engine/processors/eip/test_transactional.py -v
# Expected: 17 passed (5 Init + 2 HappyPath + 4 FailureModes + 3 PM Init + 2 PM Alias + 1 ClassVars)

# Imports OK
.venv/bin/python -c "from src.backend.dsl.engine.processors.eip import TransactionalClientProcessor, ProcessManagerProcessor; print('OK')"
.venv/bin/python -c "from src.backend.dsl.engine.processors.eip import ClaimCheckProcessor; print('OK')"

# Re-exports в __all__
.venv/bin/python -c "from src.backend.dsl.engine.processors.eip import __all__; assert 'TransactionalClientProcessor' in __all__; assert 'ProcessManagerProcessor' in __all__; print('OK')"

# Ruff clean
.venv/bin/python -m ruff check src/backend/dsl/engine/processors/eip/ tests/unit/dsl/engine/processors/eip/test_transactional.py
# Expected: All checks passed
```

S63 W3.0 [wave:s63/w3-eip-10of10]
