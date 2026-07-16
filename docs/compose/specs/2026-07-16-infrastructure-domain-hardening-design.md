# Infrastructure Domain Hardening — Design Spec

**Date:** 2026-07-16
**Status:** Approved
**Scope:** 4 waves — health unification, connector base migration, facade decomposition, driver gaps + DSL

---

## [S1] Problem

Domain analysis of `src/backend/infrastructure/` revealed:

1. **5 different health-check interfaces** coexist: `health(mode) -> HealthResult`, `health_check() -> dict`, `health() -> bool`, `healthcheck() -> bool`, `health_check() -> bool`.
2. **3 disconnected health systems**: `HealthAggregator` (used by /health endpoint), `HealthCheck` (monitoring/health_check.py, used by tech.py), `ConnectorRegistry.health_all()` (never called — dead code). `include_registry()` exists but is never invoked.
3. **37 source/sink files** do not inherit from `InfrastructureClient` (canonical ADR-022 SPI). Only 2 clients do.
4. **`infrastructure_facade.py`** — 856 LOC god-module with 80+ lazy-accessor functions.
5. **Driver gaps**: NATS source/sink exist but `nats-py` is not in dependencies. Oracle/MSSQL/MySQL/DB2 drivers missing for multi-backend gateways.

## [S2] Solution Overview

Four waves, executed sequentially. Each wave is independently verifiable.

```
Wave 1: HealthAdapter + wire include_registry() + delete old HealthCheck
    │
    ▼
Wave 2: SourceBase + SinkBase + @register_connector + migrate 37 files
    │
    ▼
Wave 3: Split infrastructure_facade.py into 6 focused modules
    │
    ▼
Wave 4: Add missing drivers + declarative health DSL
```

## [S3] Wave 1 — Health Check Unification

### HealthAdapter

**File:** `src/backend/infrastructure/clients/health_adapter.py`

Wraps legacy objects (with `health() -> bool` or `healthcheck() -> bool`) into canonical `InfrastructureClient.health(mode) -> HealthResult`.

```python
class HealthAdapter(InfrastructureClient):
    """Adapts legacy health()->bool objects to InfrastructureClient SPI."""

    def __init__(self, name: str, target: Any) -> None:
        super().__init__(name=name)
        self._target = target

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def health(self, mode: HealthMode = "fast") -> HealthResult:
        fn = getattr(self._target, "health", None) or getattr(self._target, "healthcheck", None)
        if fn is None:
            return HealthResult.failed(error="No health method", mode=mode)
        return await self._timed_health(fn, mode)
```

### Wire include_registry

**File:** `src/backend/plugins/composition/setup_infra/health.py`

Add `aggregator.include_registry(True)` after manual registrations. This connects `ConnectorRegistry.health_all()` to the `/health` endpoint.

### Delete old HealthCheck

**File:** `src/backend/infrastructure/monitoring/health_check.py` — delete entirely.
**File:** `src/backend/entrypoints/api/v1/endpoints/tech.py` — redirect `/healthcheck-*` endpoints to `HealthAggregator.check_single(name)`.

### Tests

`tests/unit/infrastructure/test_health_adapter.py` — test ok/failed/degraded paths, mode propagation, no-method edge case.

## [S4] Wave 2 — Unified Connector Base + Migration

### SourceBase

**File:** `src/backend/infrastructure/sources/base.py`

```python
class SourceBase(InfrastructureClient):
    """Base class for all message/event sources."""

    async def consume(self) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError

    async def ack(self, message_id: str) -> None: ...
    async def nack(self, message_id: str) -> None: ...
```

### SinkBase

**File:** `src/backend/infrastructure/sinks/base.py`

```python
class SinkBase(InfrastructureClient):
    """Base class for all message/event sinks."""

    async def publish(self, message: dict[str, Any]) -> bool: ...
    async def batch_publish(self, messages: list[dict[str, Any]]) -> int: ...
```

### @register_connector decorator

**File:** `src/backend/infrastructure/registry.py` — add:

```python
def register_connector(name: str, vault_path: str | None = None):
    """Decorator: auto-registers InfrastructureClient subclass in ConnectorRegistry."""
    def decorator(cls):
        original_init = cls.__init__
        def new_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            get_registry().register(self, vault_path=vault_path)
        cls.__init__ = new_init
        return cls
    return decorator
```

### Migration plan (37 files)

**Sources (23 files):** http, soap, grpc, graphql_subscription, websocket, sse, webhook, polling, webdav, nats, mq, mongo, nats_jetstream, email_imap, file_watcher, email, cdc, cdc_oracle, cdc_postgres_logical, telegram_webhook + factory + __init__

**Sinks (12 files):** http_sink, mq_sink, soap_sink, grpc_sink, s3_sink, file_sink, webhook_sink, ws_sink, email_sink, nats_jetstream, mqtt_sink + factory

Each file: inherit from SourceBase/SinkBase, implement start/stop/health(mode) via existing logic, convert `health() -> bool` to `health(mode) -> HealthResult`.

**Batch strategy:** 5-7 files per batch, each batch = one commit. Run `make test` after each batch.

## [S5] Wave 3 — Facade Decomposition

Split `core/di/providers/infrastructure_facade.py` (856 LOC) into:

| New module | Functions moved |
|------------|-----------------|
| `observability_bridge.py` | get_correlation_id, get_client_metrics, get_metrics_registry_*, get_prometheus_* |
| `resilience_bridge.py` | get_bulkhead_*, get_in_memory_resilience_profile_store_class |
| `dlq_bridge.py` | get_dlq_envelope_class, get_dlq_base_module, get_dlq_writer_class, get_dlq_reason_class |
| `health_bridge.py` | get_health_result_class, get_health_mode_class, get_health_check_factory, get_infrastructure_client_class |
| `search_bridge.py` | get_web_search_service_class, get_*_provider_class, get_search_providers_module |
| `cdc_bridge.py` | get_cdc_client_adapter_class, get_debezium_*_class |

Original `infrastructure_facade.py` → re-export shim (import from new modules) for backward-compat.

## [S6] Wave 4 — Driver Gaps + Declarative DSL

### Dependencies

- `nats-py>=2.9.0,<3.0.0` → `[project].dependencies`
- `oracledb>=2.5.0`, `aioodbc>=5.0.0`, `aiomysql>=0.2.0` → `[project.optional-dependencies].db_drivers`

### Declarative Health DSL

**File:** `src/backend/infrastructure/monitoring/health_profile.py`

```python
@dataclass
class HealthProfile:
    name: str
    mode: HealthMode = "fast"
    timeout_s: float = 1.0
    critical: bool = True

def load_health_profiles(yaml_path: Path) -> dict[str, HealthProfile]: ...
```

Profiles loaded at bootstrap, applied to registered connectors.

## [S7] Testing Strategy

- Each new base class / adapter: unit tests (pytest, `@pytest.mark.unit`)
- HealthAdapter: test with mock objects returning bool, raising exceptions, missing method
- SourceBase/SinkBase: test lifecycle (start/stop/health), ack/nack semantics
- Migration: smoke test per migrated connector (health() returns HealthResult, not bool)
- Facade decomposition: verify all re-exports still work (import test)
- DSL: test YAML parsing, profile application

## [S8] Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Migration breaks existing routes | Each batch: `make test` before commit |
| Circular imports from @register_connector | Lazy import in decorator body, not at module level |
| Backward-compat for health() -> bool callers | HealthAdapter bridges old → new; old callers unaffected |
| Facade split breaks consumers | Re-export shim preserves all existing import paths |
