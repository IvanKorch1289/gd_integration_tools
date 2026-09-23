# ADR-0331 — W9 P2-13 Phase 7: `core/di/providers/workflow.py` (602 LOC) → package split

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W9 (god-objects); V15 forbidden pattern «God-modules
  (>500 LOC)»; ADR-0328 (W9 P2-13 Phase 3 privacy split); ADR-0329 (W9 P2-13
  Phase 4 health split); ADR-0330 (W9 P2-13 Phase 5 agent_sandbox split).

## Контекст

`src/backend/core/di/providers/workflow.py` (602 LOC, top-6 god-module) —
содержит 58 provider functions grouped by concerns:

* **Workflow core** (10 funcs, ~150 LOC): action_bus/dispatcher, scheduler,
  workflow_event/state_store/row_class/state_repository/workflow_status_enum.
* **Resilience** (5 funcs, ~50 LOC): resilience_coordinator,
  resilience_components_report, rate_limiter/classes.
* **Loggers** (5 funcs, ~50 LOC): app_logger, correlation_context_setter,
  grpc_logger, stream_logger.
* **Messaging** (6 funcs, ~80 LOC): reply_channel_class, sink_factory,
  mq/ws/grpc/soap_sink_class.
* **DLQ** (3 funcs, ~60 LOC): di_bridge_dlq_module, dlq_memory_writer_module,
  dlq_envelope_class.
* **Notifications** (1 func, ~20 LOC): notifications_module.
* **Workflow factory** (1 func, ~20 LOC): workflow_factory_module.

**Проблема**:
- V15 forbidden pattern «God-modules (>500 LOC)».
- Workflow (per-domain) + messaging + DLQ mixed — different concerns.
- 58 functions в одном файле — навигация затруднена.

**History**: файл разрастался через M2-#11 batch 7-19 (DR-0321 Phase 2A)
когда misattributed providers переносились из cache.py. W9 P2-13 Phase 2A
добавил ~50 funcs, но не сделал split — только back-compat re-exports.

**Consumer audit**:
- `from src.backend.core.di.providers.workflow import X` — primary API.
- `from src.backend.core.di.providers import X` (через `__init__.py`) —
  public API.

## Решение

### Phase 7A: Split на 4 cohesion submodules

| Module | LOC est. | Содержимое |
|---|---|---|
| `workflow.py` (shim) | ~80 | thin re-exports для back-compat |
| `_workflow_core.py` | ~180 | workflow core: action_bus/dispatcher, scheduler, event/state_store, row_class, status_enum, state_repository |
| `_resilience.py` | ~50 | resilience_coordinator, components_report, rate_limiter/classes |
| `_loggers.py` | ~50 | app_logger, correlation_setter, grpc_logger, stream_logger |
| `_messaging.py` | ~110 | reply_channel_class, sink_factory, mq/ws/grpc/soap_sink_class |
| `_dlq.py` | ~60 | di_bridge_dlq_module, dlq_memory_writer_module, dlq_envelope_class |
| `_notifications.py` | ~25 | notifications_module |
| `_workflow_factory.py` | ~25 | workflow_factory_module + workflow_backend_factory |

**Total**: ~580 LOC distributed (с overhead), max per-module < 200 LOC.

### Back-compat strategy (W2 P0-3 SagaLRA Variant A pattern)

* `core/di/providers/workflow.py` → thin re-export shim.
* `core/di/providers/__init__.py` (public API) без изменений.
* Per-domain `_overrides` isolation сохранена (submodules каждый со своим).

### Что НЕ делаем

* **Не** меняем provider signatures (изменения = breaking).
* **Не** мерджим `_overrides` dict'ы (per-domain isolation required).
* **Не** удаляем deprecation warnings — все 58 functions остаются публичными.

## Альтернативы (отклонённые)

1. **Keep as-is (602 LOC)**: нарушает V15.
2. **Split per-function (58 файлов)**: не имеет смысла.
3. **Split per-sprint (cache.py история)**: те же concerns что и Phase 2A
   cache.py, может быть resolved одним split (Phase 7).

## Verification

```
compileall -q src/backend/core/di/providers/                          → exit 0
ruff check --select F401,F841,F811,E9 src/backend/core/di/providers/ → All checks passed
python -c "from src.backend.core.di.providers.workflow import get_X_provider (58 funcs)"
                                                                     → importable
pytest tests/unit/core/di/providers/test_workflow.py                  → passed
pytest tests/unit/core/di/ (per-domain override isolation tests)       → passed
```

## Roadmap (после Phase 7)

Per ADR-0328/0329/0330 roadmap:
* Phase 8: `infrastructure/clients/storage/s3_pool/client.py` (625 LOC)
  — S3 pool split.
* Phase 9: `core/security/pii_tokenizer.py` (565 LOC) — single class, harder split.

Refs: MINIMAX W9 P2-13 Phase 7, V15 forbidden pattern «god-modules»,
ADR-0316 (W2 P0-3 SagaLRA Variant A back-compat pattern), ADR-0328 (W9 P2-13
Phase 3 privacy split), ADR-0329 (W9 P2-13 Phase 4 health split),
ADR-0330 (W9 P2-13 Phase 5 agent_sandbox split).
