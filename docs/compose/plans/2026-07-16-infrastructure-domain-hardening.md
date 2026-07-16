# Infrastructure Domain Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify health-checks across all 37+ infrastructure connectors, decompose the god-facade, add missing drivers, and introduce declarative health DSL.

**Architecture:** Update Source/Sink protocols to return `HealthResult` instead of `bool`. HealthAdapter wraps any Source/Sink into `InfrastructureClient` for ConnectorRegistry. Wire `include_registry(True)` so all registered connectors appear in `/health`. Split `infrastructure_facade.py` (856 LOC) into 6 focused bridge modules.

**Tech Stack:** Python 3.14+, async-first, pytest, Pydantic, ruff, mypy

## Global Constraints

- Type hints everywhere (Python 3.14+ syntax: `int | str`, generic `class Foo[T]`)
- Async-first — no blocking I/O in async context
- `@pytest.mark.unit` on all unit tests
- `make lint && make type-check` must pass before commit
- `make format` (ruff) before commit
- Commit messages: Russian-first, conventional prefix (`feat:`, `fix:`, `refactor:`), no emoji
- Ponytail: minimal code, deletion over addition, shortest working diff wins

---

## File Structure

### New files

| File | Responsibility |
|------|----------------|
| `src/backend/infrastructure/clients/health_adapter.py` | Wraps legacy health()->bool objects into InfrastructureClient |
| `src/backend/infrastructure/sources/base.py` | SourceHealthMixin: `_timed_health()` helper |
| `src/backend/infrastructure/sinks/base.py` | SinkHealthMixin: `_timed_health()` helper |
| `src/backend/core/di/providers/observability_bridge.py` | Metrics/correlation/client_metrics lazy accessors |
| `src/backend/core/di/providers/resilience_bridge.py` | Bulkhead/CB/profile_store lazy accessors |
| `src/backend/core/di/providers/dlq_bridge.py` | DLQ envelope/writer/reason lazy accessors |
| `src/backend/core/di/providers/health_bridge.py` | HealthResult/HealthMode/factory lazy accessors |
| `src/backend/core/di/providers/search_bridge.py` | Web search providers lazy accessors |
| `src/backend/core/di/providers/cdc_bridge.py` | CDC adapter lazy accessors |
| `src/backend/infrastructure/monitoring/health_profile.py` | Declarative health-check profiles |
| `tests/unit/infrastructure/test_health_adapter.py` | HealthAdapter tests |
| `tests/unit/infrastructure/test_health_profile.py` | HealthProfile DSL tests |

### Modified files

| File | Change |
|------|--------|
| `src/backend/core/interfaces/source.py` | `health() -> bool` → `health(mode="fast") -> HealthResult` |
| `src/backend/core/interfaces/sink.py` | Same |
| `src/backend/plugins/composition/setup_infra/health.py` | Add `aggregator.include_registry(True)` |
| `src/backend/infrastructure/monitoring/health_check.py` | **Delete** |
| `src/backend/entrypoints/api/v1/endpoints/tech.py` | Redirect to HealthAggregator |
| `src/backend/core/di/providers/infrastructure_facade.py` | Thin re-export shim |
| `src/backend/core/di/providers/__init__.py` | Add new bridge modules to exports |
| `pyproject.toml` | Add `nats-py`, optional `db_drivers` extras |
| 37 source/sink files | Update `health()` signature |

---

## Task 1: Update Source/Sink Protocol Health Signature

**Covers:** [S3], [S4]

**Files:**
- Modify: `src/backend/core/interfaces/source.py:110-112`
- Modify: `src/backend/core/interfaces/sink.py:89-91`
- Test: `tests/unit/infrastructure/sources/test_protocol_health.py`

**Interfaces:**
- Produces: `Source.health(mode: HealthMode = "fast") -> HealthResult`, `Sink.health(mode: HealthMode = "fast") -> HealthResult`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/infrastructure/sources/test_protocol_health.py
"""Tests for updated Source/Sink health protocol signature."""
from __future__ import annotations

import pytest
from src.backend.core.interfaces.source import Source, SourceKind
from src.backend.core.interfaces.sink import Sink, SinkKind
from src.backend.infrastructure.clients.base_connector import HealthResult


@pytest.mark.unit
async def test_source_protocol_has_health_result_signature() -> None:
    """Source.health must accept mode kwarg and return HealthResult."""

    class StubSource:
        source_id = "test"
        kind = SourceKind.HTTP

        async def start(self, on_event) -> None: ...

        async def stop(self) -> None: ...

        async def health(self, mode="fast") -> HealthResult:
            return HealthResult.ok(latency_ms=0.1, mode=mode)

    obj = StubSource()
    assert isinstance(obj, Source)  # runtime_checkable Protocol
    result = await obj.health(mode="deep")
    assert isinstance(result, HealthResult)
    assert result.mode == "deep"


@pytest.mark.unit
async def test_sink_protocol_has_health_result_signature() -> None:
    """Sink.health must accept mode kwarg and return HealthResult."""

    class StubSink:
        sink_id = "test"
        kind = SinkKind.HTTP

        async def send(self, payload) -> object: ...

        async def health(self, mode="fast") -> HealthResult:
            return HealthResult.ok(latency_ms=0.1, mode=mode)

    obj = StubSink()
    assert isinstance(obj, Sink)
    result = await obj.health(mode="deep")
    assert isinstance(result, HealthResult)
```

- [ ] **Step 2: Run test (expect fail — old protocol returns bool)**

Run: `pytest tests/unit/infrastructure/sources/test_protocol_health.py -v`
Expected: FAIL (Protocol still has `health() -> bool`)

- [ ] **Step 3: Update Source protocol**

In `src/backend/core/interfaces/source.py`, replace lines 110-112:

```python
    async def health(self) -> bool:
        """Быстрая проверка работоспособности (для health-aggregator)."""
        ...
```

With:

```python
    async def health(self, mode: str = "fast") -> HealthResult:
        """Health-проверка канала.

        Args:
            mode: ``"fast"`` (<100ms PING) или ``"deep"`` (<2s smoke-test).
        """
        ...
```

Add import at top of file:

```python
from src.backend.infrastructure.clients.base_connector import HealthResult
```

NOTE: Use `str` not `HealthMode` in the Protocol to avoid circular import (core → infrastructure). `HealthMode = Literal["fast", "deep"]` is structurally compatible with `str`.

- [ ] **Step 4: Update Sink protocol**

Same change in `src/backend/core/interfaces/sink.py` lines 89-91:

```python
    async def health(self, mode: str = "fast") -> HealthResult:
        """Health-проверка канала.

        Args:
            mode: ``"fast"`` (<100ms PING) или ``"deep"`` (<2s smoke-test).
        """
        ...
```

Add same import.

- [ ] **Step 5: Run test — verify pass**

Run: `pytest tests/unit/infrastructure/sources/test_protocol_health.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/backend/core/interfaces/source.py src/backend/core/interfaces/sink.py tests/unit/infrastructure/sources/test_protocol_health.py
git commit -m "refactor: Source/Sink health() возвращает HealthResult вместо bool"
```

---

## Task 2: Create HealthAdapter

**Covers:** [S3]

**Files:**
- Create: `src/backend/infrastructure/clients/health_adapter.py`
- Test: `tests/unit/infrastructure/test_health_adapter.py`

**Interfaces:**
- Consumes: `InfrastructureClient` (base_connector.py), `HealthResult` (base_connector.py)
- Produces: `HealthAdapter` class — wraps any object with `health() -> bool` or `healthcheck() -> bool`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/infrastructure/test_health_adapter.py
"""Tests for HealthAdapter — bridges legacy health()->bool to InfrastructureClient."""
from __future__ import annotations

import pytest
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.clients.health_adapter import HealthAdapter


@pytest.mark.unit
async def test_adapter_wraps_health_bool_ok() -> None:
    """Adapter converts health()->True to HealthResult.ok."""

    class LegacySource:
        async def health(self) -> bool:
            return True

    adapter = HealthAdapter(name="legacy_src", target=LegacySource())
    result = await adapter.health(mode="fast")
    assert result.status == "ok"
    assert result.mode == "fast"


@pytest.mark.unit
async def test_adapter_wraps_health_bool_failed() -> None:
    """Adapter converts health()->False to HealthResult.failed."""

    class LegacySource:
        async def health(self) -> bool:
            return False

    adapter = HealthAdapter(name="legacy_src", target=LegacySource())
    result = await adapter.health(mode="fast")
    assert result.status == "failed"


@pytest.mark.unit
async def test_adapter_wraps_healthcheck_method() -> None:
    """Adapter supports healthcheck() method name (storage layer)."""

    class LegacyStorage:
        async def healthcheck(self) -> bool:
            return True

    adapter = HealthAdapter(name="legacy_storage", target=LegacyStorage())
    result = await adapter.health(mode="deep")
    assert result.status == "ok"
    assert result.mode == "deep"


@pytest.mark.unit
async def test_adapter_no_health_method() -> None:
    """Adapter returns failed when target has no health method."""

    class NoHealth:
        pass

    adapter = HealthAdapter(name="no_health", target=NoHealth())
    result = await adapter.health(mode="fast")
    assert result.status == "failed"
    assert "No health method" in (result.error or "")


@pytest.mark.unit
async def test_adapter_wraps_exception() -> None:
    """Adapter catches exceptions from legacy health()."""

    class BrokenSource:
        async def health(self) -> bool:
            raise ConnectionError("DNS resolution failed")

    adapter = HealthAdapter(name="broken", target=BrokenSource())
    result = await adapter.health(mode="fast")
    assert result.status == "failed"
    assert "ConnectionError" in (result.error or "")


@pytest.mark.unit
async def test_adapter_lifecycle() -> None:
    """Adapter start/stop are idempotent no-ops."""
    adapter = HealthAdapter(name="test", target=object())
    await adapter.start()
    assert adapter._started is True
    await adapter.stop()
    assert adapter._started is False
```

- [ ] **Step 2: Run test (expect import error)**

Run: `pytest tests/unit/infrastructure/test_health_adapter.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement HealthAdapter**

```python
# src/backend/infrastructure/clients/health_adapter.py
"""HealthAdapter — bridges legacy health()->bool objects to InfrastructureClient SPI.

Позволяет регистрировать sources/sinks/storage backends в ConnectorRegistry
без модификации их кода. Адаптер вызывает существующий health()/healthcheck()
и оборачивает результат в HealthResult с timing.

Использование::

    from src.backend.infrastructure.clients.health_adapter import HealthAdapter

    adapter = HealthAdapter(name="kafka_source", target=my_source)
    get_registry().register(adapter)
"""

from __future__ import annotations

from typing import Any

from src.backend.infrastructure.clients.base_connector import (
    HealthMode,
    HealthResult,
    InfrastructureClient,
)

__all__ = ("HealthAdapter",)


class HealthAdapter(InfrastructureClient):
    """Adapts legacy objects (health()->bool / healthcheck()->bool) к InfrastructureClient.

    * ``start``/``stop`` — idempotent no-ops (lifecycle управляется источником).
    * ``health(mode)`` — вызывает legacy-метод и оборачивает в HealthResult.
    """

    def __init__(self, name: str, target: Any) -> None:
        super().__init__(name=name)
        self._target = target

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def health(self, mode: HealthMode = "fast") -> HealthResult:
        fn = (
            getattr(self._target, "health", None)
            or getattr(self._target, "healthcheck", None)
            or getattr(self._target, "health_check", None)
        )
        if fn is None:
            return HealthResult.failed(error="No health method", mode=mode)
        return await self._timed_health(fn, mode)
```

- [ ] **Step 4: Run test — verify pass**

Run: `pytest tests/unit/infrastructure/test_health_adapter.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/backend/infrastructure/clients/health_adapter.py tests/unit/infrastructure/test_health_adapter.py
git commit -m "feat: HealthAdapter — мост legacy health()->bool к InfrastructureClient"
```

---

## Task 3: SourceHealthMixin / SinkHealthMixin

**Covers:** [S4]

**Files:**
- Create: `src/backend/infrastructure/sources/base.py`
- Create: `src/backend/infrastructure/sinks/base.py`

**Interfaces:**
- Produces: `SourceHealthMixin._timed_health(probe, mode) -> HealthResult`, `SinkHealthMixin._timed_health(probe, mode) -> HealthResult`

- [ ] **Step 1: Create SourceHealthMixin**

```python
# src/backend/infrastructure/sources/base.py
"""SourceHealthMixin — helper для sources: timing + exception handling для health().

Использование::

    class MySource(SourceHealthMixin):
        kind = SourceKind.HTTP

        async def health(self, mode="fast") -> HealthResult:
            return await self._timed_health(self._probe, mode)

        async def _probe(self) -> dict:
            return {"connections": 5}
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.backend.infrastructure.clients.base_connector import (
    HealthMode,
    HealthResult,
)

__all__ = ("SourceHealthMixin",)


class SourceHealthMixin:
    """Предоставляет ``_timed_health()`` для реализации health() в sources."""

    async def _timed_health(
        self, probe: Callable[[], Any], mode: HealthMode
    ) -> HealthResult:
        """Оборачивает probe-колбек в timing + exception handling."""
        start = time.perf_counter()
        try:
            extra = await probe() if callable(probe) else {}
            latency_ms = (time.perf_counter() - start) * 1000.0
            details = extra if isinstance(extra, dict) else {}
            return HealthResult.ok(latency_ms=latency_ms, mode=mode, **details)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
```

- [ ] **Step 2: Create SinkHealthMixin**

```python
# src/backend/infrastructure/sinks/base.py
"""SinkHealthMixin — helper для sinks: timing + exception handling для health().

Симметричен SourceHealthMixin.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.backend.infrastructure.clients.base_connector import (
    HealthMode,
    HealthResult,
)

__all__ = ("SinkHealthMixin",)


class SinkHealthMixin:
    """Предоставляет ``_timed_health()`` для реализации health() в sinks."""

    async def _timed_health(
        self, probe: Callable[[], Any], mode: HealthMode
    ) -> HealthResult:
        start = time.perf_counter()
        try:
            extra = await probe() if callable(probe) else {}
            latency_ms = (time.perf_counter() - start) * 1000.0
            details = extra if isinstance(extra, dict) else {}
            return HealthResult.ok(latency_ms=latency_ms, mode=mode, **details)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
```

- [ ] **Step 3: Commit**

```bash
git add src/backend/infrastructure/sources/base.py src/backend/infrastructure/sinks/base.py
git commit -m "feat: SourceHealthMixin/SinkHealthMixin — _timed_health() helper"
```

---

## Task 4: Wire include_registry + Delete Old HealthCheck

**Covers:** [S3]

**Files:**
- Modify: `src/backend/plugins/composition/setup_infra/health.py:151-157`
- Delete: `src/backend/infrastructure/monitoring/health_check.py`
- Modify: `src/backend/entrypoints/api/v1/endpoints/tech.py`

- [ ] **Step 1: Wire include_registry**

In `src/backend/plugins/composition/setup_infra/health.py`, after line 157 (`aggregator.register("nats", _nats_health)`), add:

```python
    # Wave 1: auto-include all ConnectorRegistry clients in /health
    aggregator.include_registry(True)
```

- [ ] **Step 2: Check tech.py dependencies on health_check.py**

Run: `rg "health_check" src/backend/entrypoints/api/v1/endpoints/tech.py`

If tech.py imports from `monitoring/health_check.py`, redirect to `HealthAggregator.check_single(name)`.

- [ ] **Step 3: Delete monitoring/health_check.py**

Delete the file. Any remaining imports should already be redirected.

- [ ] **Step 4: Run health tests**

Run: `pytest tests/unit/infrastructure/application/test_health_aggregator.py tests/unit/entrypoints/api/v1/endpoints/test_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: include_registry(True) + удалён устаревший monitoring/health_check.py"
```

---

## Task 5-9: Source Migration (5 batches)

**Covers:** [S4]

**Migration pattern** (apply to each source file):

For each source class, transform:

```python
# BEFORE (existing pattern):
async def health(self) -> bool:
    return self._broker is not None
```

Into:

```python
# AFTER:
async def health(self, mode: str = "fast") -> HealthResult:
    return await self._timed_health(lambda: self._probe_health(), mode)

async def _probe_health(self) -> dict[str, Any]:
    if self._broker is None:
        raise RuntimeError("Not started")
    return {"broker": self._transport}
```

Or for simple state-check sources:

```python
# AFTER (simple):
async def health(self, mode: str = "fast") -> HealthResult:
    if self._on_event is not None:
        return HealthResult.ok(latency_ms=0.0, mode=mode)
    return HealthResult.failed(error="Not started", mode=mode)
```

Add imports to each file:
```python
from src.backend.infrastructure.clients.base_connector import HealthResult
```

### Batch 1 (Task 5): webhook.py, http.py, mq.py, nats.py, nats_jetstream.py

Files:
- `src/backend/infrastructure/sources/webhook.py:91-92`
- `src/backend/infrastructure/sources/http.py` (inherits WebhookSource — auto-covered)
- `src/backend/infrastructure/sources/mq.py:96-97`
- `src/backend/infrastructure/sources/nats.py:232`
- `src/backend/infrastructure/sources/nats_jetstream.py:190`

For each: add HealthResult import, update health() signature, run existing tests.

- [ ] **Step 1: Migrate webhook.py**
- [ ] **Step 2: Migrate mq.py**
- [ ] **Step 3: Migrate nats.py**
- [ ] **Step 4: Migrate nats_jetstream.py**
- [ ] **Step 5: Run source tests**

Run: `pytest tests/unit/infrastructure/sources/ -v --timeout=30`
Expected: PASS (existing tests may need health() assertion updates)

- [ ] **Step 6: Commit**

```bash
git add src/backend/infrastructure/sources/
git commit -m "refactor: sources batch 1 — health() возвращает HealthResult (webhook/mq/nats)"
```

### Batch 2 (Task 6): grpc.py, soap.py, websocket.py, sse.py, graphql_subscription.py

Same migration pattern. Files:
- `src/backend/infrastructure/sources/grpc.py:93`
- `src/backend/infrastructure/sources/soap.py:82`
- `src/backend/infrastructure/sources/websocket.py:66`
- `src/backend/infrastructure/sources/sse.py`
- `src/backend/infrastructure/sources/graphql_subscription.py`

- [ ] Steps: migrate each, run tests, commit

### Batch 3 (Task 7): polling.py, webdav.py, file_watcher.py, email.py, email_imap.py

Files:
- `src/backend/infrastructure/sources/polling.py:89`
- `src/backend/infrastructure/sources/webdav.py`
- `src/backend/infrastructure/sources/file_watcher.py:257`
- `src/backend/infrastructure/sources/email.py:160`
- `src/backend/infrastructure/sources/email_imap.py`

### Batch 4 (Task 8): cdc.py, cdc_oracle.py, cdc_postgres_logical.py, telegram_webhook.py, mongo.py

Files:
- `src/backend/infrastructure/sources/cdc.py:87`
- `src/backend/infrastructure/sources/cdc_oracle.py:221`
- `src/backend/infrastructure/sources/cdc_postgres_logical.py`
- `src/backend/infrastructure/sources/telegram_webhook.py`
- `src/backend/infrastructure/sources/mongo.py:323`

---

## Task 10: Sink Migration (all 11 sinks)

**Covers:** [S4]

Files:
- `src/backend/infrastructure/sinks/http_sink.py:73-92`
- `src/backend/infrastructure/sinks/mq_sink.py:73`
- `src/backend/infrastructure/sinks/soap_sink.py:99`
- `src/backend/infrastructure/sinks/grpc_sink.py:86`
- `src/backend/infrastructure/sinks/s3_sink.py:84`
- `src/backend/infrastructure/sinks/file_sink.py:111`
- `src/backend/infrastructure/sinks/webhook_sink.py:128`
- `src/backend/infrastructure/sinks/ws_sink.py:67`
- `src/backend/infrastructure/sinks/email_sink.py:124`
- `src/backend/infrastructure/sinks/nats_jetstream.py:122`
- `src/backend/infrastructure/sinks/mqtt_sink.py:136`

Same migration pattern as sources. HttpSink as example:

```python
# BEFORE (http_sink.py):
async def health(self) -> bool:
    try:
        async with OutboundHttpClient(...) as client:
            response = await client.request("HEAD", self.url)
    except Exception:
        return False
    return response.status_code < 500

# AFTER:
async def health(self, mode: str = "fast") -> HealthResult:
    async def _probe():
        import httpx
        from src.backend.core.net import OutboundHttpClient
        async with OutboundHttpClient(timeout=httpx.Timeout(self.timeout)) as client:
            response = await client.request("HEAD", self.url)
        if response.status_code >= 500:
            raise RuntimeError(f"HTTP {response.status_code}")
        return {"status_code": response.status_code}
    return await self._timed_health(_probe, mode)
```

- [ ] Steps: migrate each sink, run `pytest tests/unit/infrastructure/sinks/ -v`, commit

---

## Task 11: Facade Decomposition

**Covers:** [S5]

**Files:**
- Create: 6 new bridge modules in `src/backend/core/di/providers/`
- Modify: `src/backend/core/di/providers/infrastructure_facade.py` → thin re-export shim
- Modify: `src/backend/core/di/providers/__init__.py`

- [ ] **Step 1: Read current facade to map all functions to categories**

Run: `rg "^def get_" src/backend/core/di/providers/infrastructure_facade.py`

- [ ] **Step 2: Create 6 bridge modules**

For each module, move related `get_*` functions from infrastructure_facade.py. Each function body stays the same (lazy import + return). Original module becomes re-export shim.

- [ ] **Step 3: Update __init__.py exports**

- [ ] **Step 4: Verify all imports still work**

Run: `python -c "from src.backend.core.di.providers.infrastructure_facade import *; print('OK')"`
Run: `make lint && make type-check`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/core/di/providers/
git commit -m "refactor: infrastructure_facade.py (856 LOC) → 6 focused bridge modules"
```

---

## Task 12: Driver Dependencies

**Covers:** [S6]

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add nats-py to dependencies**

In `pyproject.toml`, after `"aiomqtt>=2.0.0,<3.0.0",` add:
```toml
    "nats-py>=2.9.0,<3.0.0",  # NATS source/sink (infrastructure/sources/nats.py)
```

- [ ] **Step 2: Add optional db_drivers extras**

After `[project.optional-dependencies].ai` section, add:
```toml
db_drivers = [
    "oracledb>=2.5.0,<3.0.0",     # Oracle (CDC, external_db)
    "aioodbc>=5.0.0,<6.0.0",      # MSSQL
    "aiomysql>=0.2.0,<1.0.0",     # MySQL
]
```

- [ ] **Step 3: Verify lock file not broken**

Run: `uv lock --check 2>/dev/null || echo "Lock file needs update — coordinated with Sprint 36"`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: добавлен nats-py + optional db_drivers extras (oracledb/aioodbc/aiomysql)"
```

---

## Task 13: Declarative Health DSL

**Covers:** [S6]

**Files:**
- Create: `src/backend/infrastructure/monitoring/health_profile.py`
- Test: `tests/unit/infrastructure/test_health_profile.py`

**Interfaces:**
- Produces: `HealthProfile` dataclass, `load_health_profiles(path) -> dict[str, HealthProfile]`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/infrastructure/test_health_profile.py
from __future__ import annotations
from pathlib import Path
import pytest
from src.backend.infrastructure.monitoring.health_profile import (
    HealthProfile,
    load_health_profiles,
)


@pytest.mark.unit
def test_default_profile() -> None:
    p = HealthProfile(name="redis")
    assert p.mode == "fast"
    assert p.timeout_s == 1.0
    assert p.critical is True


@pytest.mark.unit
def test_load_profiles_from_yaml(tmp_path: Path) -> None:
    yaml_content = """
health_checks:
  kafka_main:
    mode: deep
    timeout: 2.0
    critical: true
  redis_cache:
    mode: fast
    timeout: 0.5
    critical: false
"""
    f = tmp_path / "health.yaml"
    f.write_text(yaml_content)
    profiles = load_health_profiles(f)
    assert "kafka_main" in profiles
    assert profiles["kafka_main"].mode == "deep"
    assert profiles["kafka_main"].timeout_s == 2.0
    assert profiles["redis_cache"].critical is False
```

- [ ] **Step 2: Run test (expect import error)**

- [ ] **Step 3: Implement HealthProfile**

```python
# src/backend/infrastructure/monitoring/health_profile.py
"""Declarative health-check profiles (Wave 4).

YAML-конфиг для настройки health-check параметров коннекторов::

    health_checks:
      kafka_main:
        mode: deep
        timeout: 2.0
        critical: true
      redis_cache:
        mode: fast
        timeout: 0.5
        critical: false
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.backend.infrastructure.clients.base_connector import HealthMode

__all__ = ("HealthProfile", "load_health_profiles")


@dataclass(slots=True)
class HealthProfile:
    """Конфигурация health-check для одного коннектора."""

    name: str
    mode: HealthMode = "fast"
    timeout_s: float = 1.0
    critical: bool = True


def load_health_profiles(yaml_path: Path) -> dict[str, HealthProfile]:
    """Загружает health-профили из YAML-файла."""
    data: dict[str, Any] = yaml.safe_load(yaml_path.read_text()) or {}
    raw_profiles = data.get("health_checks", {})
    profiles: dict[str, HealthProfile] = {}
    for name, cfg in raw_profiles.items():
        profiles[name] = HealthProfile(
            name=name,
            mode=cfg.get("mode", "fast"),
            timeout_s=cfg.get("timeout", 1.0),
            critical=cfg.get("critical", True),
        )
    return profiles
```

- [ ] **Step 4: Run test — verify pass**

- [ ] **Step 5: Commit**

```bash
git add src/backend/infrastructure/monitoring/health_profile.py tests/unit/infrastructure/test_health_profile.py
git commit -m "feat: декларативный health DSL — HealthProfile + YAML loader"
```

---

## Verification

After all tasks:

- [ ] `make lint` — PASS
- [ ] `make type-check` — PASS
- [ ] `make test` — PASS
- [ ] No `from src.backend.infrastructure` in `core/` increased (target: ≤15)
- [ ] `monitoring/health_check.py` deleted
- [ ] All sources/sinks return `HealthResult` from `health()`
- [ ] `include_registry(True)` wired in bootstrap
