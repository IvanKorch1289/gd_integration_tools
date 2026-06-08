# ADR-0097: Fallback logging sink (formalize existing production-ready implementation)

**Date:** 2026-06-08
**Status:** Accepted (S71 W1 — formalize decision, S68 W1 backlog)
**Sprint:** S71
**Deciders:** core/observability team
**Supersedes:** — (formalizes existing router + disk_rotating + stdlib_backend)
**Related:** ADR-0051, router.py, disk_rotating.py, stdlib_backend.py

## Context

Backlog S68-W1: "Fallback logging sink" (от роевого анализа V22).
Подразумевалось что logging теряет сообщения при недоступности
centralized log aggregation (Graylog) или structlog.

Audit проведён 2026-06-08 — **Fallback logging sink ALREADY
PRODUCTION-READY** (1281 LOC, 6 модулей).

**Components (verified wc -l):**
```
src/backend/infrastructure/logging/router.py                       312 LOC
src/backend/infrastructure/logging/batching_router.py              150 LOC
src/backend/infrastructure/logging/backends/disk_rotating.py       128 LOC
src/backend/infrastructure/logging/backends/graylog_gelf.py        395 LOC
src/backend/infrastructure/logging/stdlib_backend.py               132 LOC
src/backend/infrastructure/logging/factory.py                      164 LOC
Total:                                                            1281 LOC
```

**Plus:**
* `src/backend/infrastructure/observability/structlog_batching.py` (structlog batching)
* `src/backend/core/resilience/degradation.py` (degradation framework)
* `src/backend/core/utils/redis_fallback.py` (Redis fallback pattern)
* `src/backend/infrastructure/external_apis/logging_service.py` (logging API)

## Decision

Признать Fallback logging sink PRODUCTION-READY. Реализация закрыта.

**Architecture (3-tier fallback):**
1. **Primary**: Graylog GELF (через `graylog_gelf.py` + `batching_router.py`)
2. **Fallback 1**: DiskRotatingLogSink (`disk_rotating.py`) — JSON в
   ротируемый файл (50 MiB × 7 backups = 350 MiB max)
3. **Fallback 2**: stdlib_backend — если structlog недоступен

**Features (verified):**
* **Auto-switch** — router переключается на fallback при failure
  (graylog_gelf.py: "router переключился на disk-fallback задолго до этого")
* **Async-friendly** — `asyncio.to_thread` обёртка для
  RotatingFileHandler (не блокирует event loop)
* **No message loss** — `batching_router.py` queue-based, retries
* **JSON structured** — orjson OPT_NAIVE_UTC для fast serialization
* **Stdlib fallback** — `stdlib_backend.py` сохраняет handlers
  (QueueListener, ContextFilter) если structlog unavailable
* **TTL via file rotation** — 50 MiB × 7 backups = авто-архив

**Router state machine (router.py):**
```
HEALTHY (Graylog) → DEGRADED (disk) → RECOVERED (back to Graylog)
```

**Usage:**
```python
from src.backend.infrastructure.logging.factory import get_log_manager
log_manager = get_log_manager()
# Auto-fallback transparent: если Graylog down, logs идут в disk.
log_manager.info("user_action", user_id=123, action="login")
```

## Consequences

### Positive

* No message loss: 3-tier fallback chain
* No event loop blocking: async-friendly file I/O
* Recovery: auto-switch back to primary при восстановлении
* Stdlib fallback: graceful degradation if structlog missing
* Disk rotation: bounded local storage (350 MiB max)
* Structured JSON: orjson fast serialization

### Negative

* Disk fallback может заполниться при долгом Graylog outage
* Нет remote archival (S3) при disk overflow
* Stdlib fallback теряет structlog features (ContextVars, processors)

### Neutral

* 1281 LOC distributed across 6 модулей
* `core/resilience/degradation.py` = общий degradation framework

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| `LogRouter` (auto-switch) | DONE | infrastructure/logging/router.py |
| `BatchingRouter` (queue-based) | DONE | infrastructure/logging/batching_router.py |
| `DiskRotatingLogSink` (fallback 1) | DONE | infrastructure/logging/backends/disk_rotating.py |
| `GraylogGelfSink` (primary) | DONE | infrastructure/logging/backends/graylog_gelf.py |
| `StdlibBackend` (fallback 2) | DONE | infrastructure/logging/stdlib_backend.py |
| `get_log_manager()` factory | DONE | infrastructure/logging/factory.py |
| `LogSink` Protocol interface | DONE | core/interfaces/log_sink.py |
| `structlog_batching.py` (batched writes) | DONE | infrastructure/observability/structlog_batching.py |
| `degradation.py` (framework) | DONE | core/resilience/degradation.py |
| `logging_service.py` (API endpoint) | DONE | infrastructure/external_apis/logging_service.py |
| S3 archival for disk overflow | TODO | out of scope |
| Per-tenant log routing | TODO | out of scope |
| Log admin UI (Streamlit) | TODO | out of scope |
| Log loss alert (Prometheus) | TODO | out of scope |

## References

* `src/backend/infrastructure/logging/router.py` (312 LOC)
* `src/backend/infrastructure/logging/batching_router.py` (150 LOC)
* `src/backend/infrastructure/logging/backends/disk_rotating.py` (128 LOC)
* `src/backend/infrastructure/logging/backends/graylog_gelf.py` (395 LOC)
* `src/backend/infrastructure/logging/stdlib_backend.py` (132 LOC)
* `src/backend/infrastructure/logging/factory.py` (164 LOC)
* `src/backend/infrastructure/observability/structlog_batching.py`
* `src/backend/core/resilience/degradation.py`
* `src/backend/core/utils/redis_fallback.py`
* `src/backend/core/interfaces/log_sink.py` (Protocol)
* `src/backend/infrastructure/external_apis/logging_service.py`
* ADR-0051 (parent: in-house observability primitives)
