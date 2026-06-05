"""Unit-tests for resilience health check providers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.resilience.health import (
    _STATUS_MAP,
    _component_to_dict,
    build_resilience_health_check,
    register_resilience_health_checks,
    resilience_components_report,
)


def test_status_map() -> None:
    assert _STATUS_MAP["normal"] == "ok"
    assert _STATUS_MAP["degraded"] == "degraded"
    assert _STATUS_MAP["down"] == "error"


def test_component_to_dict() -> None:
    comp = SimpleNamespace(
        name="db",
        degradation="degraded",
        breaker_state="open",
        mode="auto",
        chain=["pg"],
        last_used_backend="pg",
    )
    d = _component_to_dict(comp)
    assert d["name"] == "db"
    assert d["status"] == "degraded"
    assert d["details"]["breaker_state"] == "open"


@pytest.mark.asyncio
async def test_build_health_check_known_component() -> None:
    coord = MagicMock()
    coord.status.return_value = {
        "db": SimpleNamespace(
            name="db",
            degradation="normal",
            breaker_state="closed",
            mode="auto",
            chain=["pg"],
            last_used_backend="pg",
        )
    }
    check = build_resilience_health_check("db", coordinator=coord)
    result = await check()
    assert result["status"] == "ok"
    assert result["name"] == "db"


@pytest.mark.asyncio
async def test_build_health_check_unknown_component() -> None:
    coord = MagicMock()
    coord.status.return_value = {}
    check = build_resilience_health_check("mq", coordinator=coord)
    result = await check(mode="fast")
    assert result["status"] == "unknown"
    assert result["mode"] == "fast"


def test_register_health_checks() -> None:
    coord = MagicMock()
    coord.list_components.return_value = ["db", "cache"]
    aggregator = MagicMock()
    register_resilience_health_checks(aggregator, coordinator=coord)
    assert aggregator.register.call_count == 2


def test_resilience_components_report() -> None:
    coord = MagicMock()
    coord.status.return_value = {
        "db": SimpleNamespace(
            name="db",
            degradation="normal",
            breaker_state="closed",
            mode="auto",
            chain=["pg"],
            last_used_backend="pg",
        )
    }
    report = resilience_components_report(coordinator=coord)
    assert "db" in report
    assert report["db"]["status"] == "ok"
