"""Тесты processor health-checks (T3 ratchet: health.py 54%→≥85%).

Каждый check — pure function от настроек + сети; тестируются ветки:
не настроен -> ok=True ("not configured"), настроен + сеть OK -> True,
настроен + сеть недоступна -> False. Сеть мокается на _http_get/_tcp_connect.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.services.ops import health as health_mod
from src.backend.services.ops.health import (
    _check_clickhouse,
    _check_graylog,
    _check_kafka_schema_registry,
    _check_nats,
    _check_redis_cluster,
    _check_temporal_server,
    _check_vault_sealed,
)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Мок _http_get/_tcp_connect: возвращает (200, ok) и пишет запросы."""
    calls: list[str] = []

    async def fake_http(url: str, timeout: float = 5.0) -> tuple[int, str]:
        calls.append(url)
        return 200, "ok"

    async def fake_tcp(host: str, port: int, timeout: float = 5.0) -> None:
        calls.append(f"tcp:{host}:{port}")

    monkeypatch.setattr(health_mod, "_http_get", fake_http)
    monkeypatch.setattr(health_mod, "_tcp_connect", fake_tcp)
    return calls


# ── kafka schema registry ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_kafka_no_url_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """settings.queue без schema_registry_url -> ok=False (не настроен)."""
    fake_settings = SimpleNamespace(queue=SimpleNamespace(schema_registry_url=None))
    monkeypatch.setattr("src.backend.core.config.settings.settings", fake_settings)
    result = await _check_kafka_schema_registry()
    assert result.ok is False
    assert "не настроен" in result.reason


@pytest.mark.asyncio
async def test_kafka_healthy(no_network: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = SimpleNamespace(
        queue=SimpleNamespace(schema_registry_url="http://sr:8081"),
    )
    monkeypatch.setattr("src.backend.core.config.settings.settings", fake_settings)
    result = await _check_kafka_schema_registry()
    assert result.ok is True
    assert any("sr:8081" in c for c in no_network)


# ── temporal ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_temporal_no_host_false() -> None:
    result = await _check_temporal_server()
    assert result.ok is False


@pytest.mark.asyncio
async def test_temporal_tcp_ok_true(
    no_network: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings = SimpleNamespace(
        workflow=SimpleNamespace(host="temporal:7233"),
    )
    monkeypatch.setattr("src.backend.core.config.settings.settings", fake_settings)
    result = await _check_temporal_server()
    assert result.ok is True


# ── vault ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vault_not_configured_ok_true() -> None:
    result = await _check_vault_sealed()
    assert result.ok is True
    assert "not configured" in result.reason


# ── clickhouse ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clickhouse_not_configured_ok_true() -> None:
    result = await _check_clickhouse()
    assert result.ok is True
    assert "not configured" in result.reason


# ── redis ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_not_configured_ok_true() -> None:
    result = await _check_redis_cluster()
    assert result.ok is True
    assert "not configured" in result.reason


# ── nats ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nats_not_configured_ok_true() -> None:
    result = await _check_nats()
    assert result.ok is True
    assert "not configured" in result.reason


# ── graylog ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graylog_not_configured_ok_true() -> None:
    result = await _check_graylog()
    assert result.ok is True
    assert "not configured" in result.reason
