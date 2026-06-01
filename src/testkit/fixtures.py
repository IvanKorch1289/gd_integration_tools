"""Pytest fixtures for recorder/replay functionality (K5 S19 W3, S-L10-1).

These fixtures are automatically registered via the
``src.testkit.pytest_plugin`` entry-point when the package is installed.
Plugin authors can use them by accepting the fixture names as function
arguments in their tests.

Example::

    import pytest
    from src.testkit.recorder import HARRecorder

    @pytest.mark.asyncio
    async def test_external_api(har_recorder, har_cassette_path, httpx_async_client):
        async with har_recorder.async_session(httpx_async_client) as recorder:
            await httpx_async_client.get("https://api.example.com/health")
        recorder.cassette.save(har_cassette_path)

Fixtures provided:

* ``har_recorder`` — returns :class:`HARRecorder` with ``mask_secrets=True``.
* ``har_cassette_path`` — returns a :class:`pathlib.Path` in pytest's
  ``tmp_path`` directory, named ``cassette.har.json``.
* ``memory_metrics`` — returns a fresh :class:`MemoryMetricsBackend` instance.
* ``audit_events`` — returns an empty list that code under test can append to
  via an ``audit_callback``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testkit.recorder import HARRecorder
from src.backend.infrastructure.observability.memory_metrics import MemoryMetricsBackend

__all__ = ("har_recorder", "har_cassette_path", "memory_metrics", "audit_events")


@pytest.fixture
def har_recorder() -> HARRecorder:
    """Return a :class:`HARRecorder` with ``mask_secrets=True`` by default.

    Records HTTP requests/responses made through the returned client
    into the ``har_recorder.cassette`` attribute.
    """
    return HARRecorder(mask_secrets=True)


@pytest.fixture
def har_cassette_path(tmp_path: Path) -> Path:
    """Return a path in the pytest temp directory for saving HAR cassettes.

    The file is named ``cassette.har.json`` and is unique per test function.
    """
    return tmp_path / "cassette.har.json"


@pytest.fixture
def memory_metrics() -> MemoryMetricsBackend:
    """Return a fresh :class:`MemoryMetricsBackend` for each test.

    The backend is pre-reset (empty counters/gauges/histograms).
    Use :meth:`MemoryMetricsBackend.snapshot` to inspect recorded metrics.
    """
    backend = MemoryMetricsBackend()
    backend.reset()
    return backend


@pytest.fixture
def audit_events() -> list[dict[str, Any]]:
    """Return an empty list that can be passed as ``audit_callback``.

    Code under test can call ``audit_callback(record)`` to append
    audit records for later assertion via :func:`src.testkit.assert_audit_event`.

    Example::

        events = audit_events()
        gateway = AuthorizationGateway(
            capability_gateway=gate,
            audit_callback=events.append,
        )
        await gateway.authorize(principal="p1", resource="db.read", action="check")
        assert_audit_event(events, event="authorization.decision", outcome="allow")
    """
    return []
