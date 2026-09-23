# ADR-0329 — W9 P2-13 Phase 4: `services/ops/health.py` (609 LOC) → package split

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W9 (god-objects); V15 forbidden pattern «God-modules
  (>500 LOC)»; ADR-0328 (W9 P2-13 Phase 3 privacy split).

## Контекст

`src/backend/services/ops/health.py` (609 LOC, top-4 god-module) — содержит
8 service-specific health checks + 1 main service class + utilities:

* 1 dataclass: `ProcessorHealthResult`
* 2 utility functions: `_http_get`, `_tcp_connect`
* 1 service class: `ProcessorHealthService` (lifecycle + check orchestration)
* 8 health check functions: `_check_kafka_schema_registry`,
  `_check_temporal_server`, `_check_vault_sealed`, `_check_clickhouse`,
  `_check_redis_cluster`, `_check_nats`, `_check_graylog`, + 1 inline.
* 2 module-level helpers: `_is_strict_mode`, `get_processor_health_service`

**Проблема**:
- V15 forbidden pattern «God-modules (>500 LOC) — split на семейные модули».
- 609 LOC нарушает threshold.
- 8 checks mixed в одном файле — каждое изменение touch большой файл.
- Check functions cohesive (все per-service health probes), но orchestration
  logic отделена (ProcessorHealthService).

**Consumer audit**:
- `from src.backend.services.ops.health import ProcessorHealthService,
  ProcessorHealthResult, get_processor_health_service` — primary API.

External importers:
- `src/backend/services/ops/` — re-export.
- `src/backend/entrypoints/api/v1/endpoints/health.py` — uses service.
- `src/backend/services/ops/__init__.py` — likely re-exports.

## Решение

### Phase 4A: Split на 4 cohesion modules

| Module | LOC est. | Содержимое |
|---|---|---|
| `health.py` (shim) | ~40 | thin re-exports для back-compat |
| `_types.py` | ~50 | `ProcessorHealthResult` dataclass |
| `_http.py` | ~60 | `_http_get`, `_tcp_connect` utilities |
| `_service.py` | ~180 | `ProcessorHealthService`, `_is_strict_mode`, `get_processor_health_service` |
| `_checks.py` | ~340 | 8 health check functions (Kafka, Temporal, Vault, ClickHouse, Redis, NATS, Graylog, etc.) |

**Total**: ~670 LOC distributed (с overhead), но max per-module < 350 LOC.

### Co-location strategy

`health.py` остаётся как **thin re-export shim** (аналогично W9 P2-13 Phase 3):
- `from ._types import ProcessorHealthResult`
- `from ._http import _http_get, _tcp_connect`
- `from ._service import ProcessorHealthService, get_processor_health_service, _is_strict_mode`
- `from ._checks import (8 check functions)`

Public API через `services.ops.health` без изменений. All 8 check functions
остаются private (`_check_*`) — не публичный API, internal к service.

### Что НЕ делаем

* **Не** рефакторим health check logic (изменения semantics = breaking).
* **Не** мерджим похожие check patterns в общий helper (premature abstraction).
* **Не** удаляем inline checks (5 checks inline + 3 standalone functions = 8 total).

## Альтернативы (отклонённые)

1. **Keep as-is (609 LOC)**: нарушает V15.
2. **Split per-check (8 файлов)**: too granular; cohesive group лучше.
3. **Merge с Phase 3 privacy split**: разные concerns (privacy vs ops), нельзя.
4. **Move to extensions/**: ops/health — universal, не business-specific.

## Verification

```
compileall -q src/backend/services/ops/                          → exit 0
ruff check --select F401,F841,F811,E9 src/backend/services/ops/ → All checks passed
python -c "from src.backend.services.ops.health import ProcessorHealthService, ProcessorHealthResult, get_processor_health_service"
                                                                  → importable
pytest tests/unit/services/ops/health/                            → passed
pytest tests/unit/entrypoints/api/v1/endpoints/test_health.py    → passed
```

## Roadmap (после Phase 4)

Per ADR-0328 roadmap:
* Phase 5: `services/ai/agent_sandbox.py` (601 LOC) — sandbox split.
* Phase 6: `core/ai/skill_registry.py` (614 LOC) — skill registry split.
* Phase 7: `core/di/providers/workflow.py` (602 LOC после Phase 2) — workflow split
  (если не уменьшится после Phase 3B shim removal).

Refs: MINIMAX W9 P2-13 Phase 4, V15 forbidden pattern «god-modules»,
ADR-0316 (W2 P0-3 SagaLRA Variant A back-compat pattern), ADR-0328 (W9 P2-13
Phase 3 privacy split).
