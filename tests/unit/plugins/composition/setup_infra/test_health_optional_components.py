"""Health-checks опциональных компонентов: отключён → ``skipped``.

Регрессия (стенд 2026-10-29): на профиле ``dev_light`` (``fs.provider=local``,
S3-совместимый бэкенд не используется; Redis выключен; NATS не настроен)
``GET /health/ready`` отдавал 503 ``{"status": "down", ..., "s3": {"status":
"error", "error": "... NoSuch API S3"}}``. Отключённые опциональные
компоненты (redis/queue/kafka) должны помечаться ``skipped``, а не
``error`` — иначе стенд без этих сервисов никогда не станет ready.

Дополнительно: проверка Redis игнорировала результат ``ping()`` и
сообщала ``ok`` даже при недоступном Redis; проверка NATS использовала
захардкоженный ``localhost:4222`` вместо настроек профиля.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.plugins.composition.setup_infra import health as health_mod

__all__ = ("TestNatsHealthCheck", "TestRedisHealthCheck", "TestS3HealthCheck")


class _FakeAggregator:
    """Заглушка ``HealthAggregator`` — собирает зарегистрированные проверки."""

    def __init__(self) -> None:
        self.checks: dict[str, Any] = {}

    def register(self, name: str, fn: Any) -> None:
        """Запомнить health-check по имени."""
        self.checks[name] = fn

    def include_registry(self, enabled: bool = True) -> None:
        """No-op (реальный агрегатор подключает ConnectorRegistry)."""


async def _run_check(name: str) -> dict[str, Any]:
    """Зарегистрировать health-checks и выполнить проверку ``name``."""
    aggregator = _FakeAggregator()
    with patch(
        "src.backend.infrastructure.application.health_aggregator.get_health_aggregator",
        return_value=aggregator,
    ):
        await health_mod._register_health_checks()
    return await aggregator.checks[name]()


class TestS3HealthCheck:
    """S3-компонент в отчёте ``/health/ready``."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_local_provider_is_skipped(self, monkeypatch: Any) -> None:
        """``provider=local`` (dev_light) → skipped, без обращения к S3."""
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(settings.storage, "provider", "local")
        client = MagicMock()
        with patch.object(health_mod, "get_s3_client", return_value=client):
            result = await _run_check("s3")
        assert result["status"] == "skipped"
        assert "reason" in result
        client.check_bucket_exists.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_disabled_fs_is_skipped(self, monkeypatch: Any) -> None:
        """``fs.enabled=false`` → skipped."""
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(settings.storage, "enabled", False)
        result = await _run_check("s3")
        assert result["status"] == "skipped"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_enabled_s3_ok(self, monkeypatch: Any) -> None:
        """Включённый S3 с успешной проверкой → ok."""
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(settings.storage, "enabled", True)
        monkeypatch.setattr(settings.storage, "provider", "minio")
        client = MagicMock()
        client.check_bucket_exists = AsyncMock(return_value=True)
        with patch.object(health_mod, "get_s3_client", return_value=client):
            result = await _run_check("s3")
        assert result["status"] == "ok"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_enabled_s3_error_is_reported(self, monkeypatch: Any) -> None:
        """Включённый S3 с ошибкой проверки → error (не skipped)."""
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(settings.storage, "enabled", True)
        monkeypatch.setattr(settings.storage, "provider", "minio")
        client = MagicMock()
        client.check_bucket_exists = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(health_mod, "get_s3_client", return_value=client):
            result = await _run_check("s3")
        assert result["status"] == "error"
        assert "boom" in result["error"]


class TestRedisHealthCheck:
    """Redis-компонент в отчёте ``/health/ready``."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_disabled_redis_is_skipped(self, monkeypatch: Any) -> None:
        """``redis.enabled=false`` → skipped, без попытки подключения."""
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(settings.redis, "enabled", False)
        with patch.object(health_mod, "get_redis_client") as get_client:
            result = await _run_check("redis")
        assert result["status"] == "skipped"
        get_client.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_enabled_redis_ok(self, monkeypatch: Any) -> None:
        """Включённый Redis с успешным ping → ok."""
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(settings.redis, "enabled", True)
        client = MagicMock()
        client._raw_client = None
        client.ping = AsyncMock(return_value=True)
        with patch.object(health_mod, "get_redis_client", return_value=client):
            result = await _run_check("redis")
        assert result["status"] == "ok"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ping_false_is_error(self, monkeypatch: Any) -> None:
        """``ping()`` вернул False (Redis недоступен) → error, не ok."""
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(settings.redis, "enabled", True)
        client = MagicMock()
        client._raw_client = None
        client.ping = AsyncMock(return_value=False)
        with patch.object(health_mod, "get_redis_client", return_value=client):
            result = await _run_check("redis")
        assert result["status"] == "error"


class TestNatsHealthCheck:
    """NATS-компонент в отчёте ``/health/ready``."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_not_configured_is_skipped(self) -> None:
        """NATS не настроен в профиле → skipped (без TCP-пробы)."""
        result = await _run_check("nats")
        assert result["status"] == "skipped"
        assert "reason" in result

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_configured_nats_is_probed(self, monkeypatch: Any) -> None:
        """Настроенный NATS → TCP-проба на настроенный host:port."""
        monkeypatch.setattr(health_mod, "_nats_endpoint", lambda: ("127.0.0.1", 4222))
        result = await _run_check("nats")
        assert result["status"] in ("ok", "error")
        assert "skipped" not in result["status"]
