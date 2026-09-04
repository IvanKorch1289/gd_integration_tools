"""Unit tests for TechService (services/core/tech.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.core.tech import TechService, get_tech_service


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    import src.backend.services.core.tech as _mod

    _mod._instance = None
    yield
    _mod._instance = None


@pytest.fixture()
def service() -> TechService:
    return TechService()


# ── link generators ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_log_storage_link(service: TechService) -> None:
    with patch("src.backend.services.core.tech.settings") as mock_settings:
        with patch("src.backend.services.core.tech.generate_link_page") as mock_gen:
            mock_settings.logging.host = "http://logs"
            mock_settings.logging.port = 8080
            await service.get_log_storage_link()
            mock_gen.assert_called_once_with("http://logs:8080", "Хранилище логов")


@pytest.mark.asyncio
async def test_get_file_storage_link(service: TechService) -> None:
    with patch("src.backend.services.core.tech.settings") as mock_settings:
        with patch("src.backend.services.core.tech.generate_link_page") as mock_gen:
            mock_settings.storage.interface_endpoint = "http://storage"
            await service.get_file_storage_link()
            mock_gen.assert_called_once_with("http://storage", "Файловое хранилище")


@pytest.mark.asyncio
async def test_get_queue_monitor_link(service: TechService) -> None:
    with patch("src.backend.services.core.tech.settings") as mock_settings:
        with patch("src.backend.services.core.tech.generate_link_page") as mock_gen:
            mock_settings.queue.queue_ui_url = "http://queue"
            await service.get_queue_monitor_link()
            mock_gen.assert_called_once_with("http://queue", "Мониторинг очередей")


@pytest.mark.asyncio
async def test_get_langfuse_link(service: TechService) -> None:
    with patch("src.backend.services.core.tech.settings") as mock_settings:
        with patch("src.backend.services.core.tech.generate_link_page") as mock_gen:
            mock_settings.app.langfuse_url = "http://lf"
            await service.get_langfuse_link()
            mock_gen.assert_called_once_with(
                "http://lf", "LangFuse — LLM Observability",
            )


@pytest.mark.asyncio
async def test_get_langgraph_link(service: TechService) -> None:
    with patch("src.backend.services.core.tech.settings") as mock_settings:
        with patch("src.backend.services.core.tech.generate_link_page") as mock_gen:
            mock_settings.app.langgraph_url = "http://lg"
            await service.get_langgraph_link()
            mock_gen.assert_called_once_with(
                "http://lg", "LangGraph Studio — AI Agents",
            )


# ── health checks (T7 вариант (a): HealthAggregator) ────────────


@pytest.fixture()
def aggregator_override():
    """DI-override: подставляем mock-агрегатор, чистим после теста."""
    from src.backend.core.di.providers import set_health_aggregator_provider
    from src.backend.core.di.providers.cache import _overrides

    aggregator = AsyncMock()
    set_health_aggregator_provider(aggregator)
    yield aggregator
    _overrides.pop("health_aggregator", None)


@pytest.mark.asyncio
async def test_check_database_healthy(service: TechService, aggregator_override) -> None:
    aggregator_override.check_single = AsyncMock(
        return_value={"name": "db_main", "status": "ok", "latency_ms": 1.0}
    )
    assert await service.check_database() is True
    aggregator_override.check_single.assert_awaited_once_with("db_main", mode="fast")


@pytest.mark.asyncio
async def test_check_redis_unhealthy(service: TechService, aggregator_override) -> None:
    aggregator_override.check_single = AsyncMock(
        return_value={"name": "redis_cache", "status": "error", "error": "refused"}
    )
    assert await service.check_redis() is False


@pytest.mark.asyncio
async def test_check_unknown_component_is_false(
    service: TechService, aggregator_override
) -> None:
    """Незарегистрированная компонента (graylog/logging_service) → False."""
    aggregator_override.check_single = AsyncMock(
        return_value={
            "name": "logging_service",
            "status": "error",
            "error": "Component not registered",
        }
    )
    assert await service.check_graylog() is False


@pytest.mark.asyncio
async def test_check_s3_maps_to_s3_main(
    service: TechService, aggregator_override
) -> None:
    aggregator_override.check_single = AsyncMock(
        return_value={"name": "s3_main", "status": "ok"}
    )
    assert await service.check_s3() is True
    aggregator_override.check_single.assert_awaited_once_with("s3_main", mode="fast")


@pytest.mark.asyncio
async def test_check_all_services_maps_statuses(
    service: TechService, aggregator_override
) -> None:
    aggregator_override.check_all = AsyncMock(
        return_value={
            "status": "error",
            "components": {
                "db_main": {"name": "db_main", "status": "ok"},
                "smtp_main": {"name": "smtp_main", "status": "error"},
            },
        }
    )
    result = await service.check_all_services()
    assert result == {"db_main": True, "smtp_main": False}


# ── degradation snapshot ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_degradation_snapshot(service: TechService) -> None:
    with patch(
        "src.backend.core.resilience.graceful_degradation.get_graceful_degradation_registry",
    ) as mock_reg:
        mock_reg.return_value.snapshot.return_value = {"feature": {"state": "ok"}}
        result = await service.get_degradation_snapshot()
        assert result == {"feature": {"state": "ok"}}


# ── custom tables ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_all_custom_tables(service: TechService) -> None:
    from enum import Enum

    class FakeModel:
        __tablename__ = "orders"

    class FakeEnum(Enum):
        # Production does ``m.value.__tablename__`` — the enum member's value
        # must be the model object itself (not a SimpleNamespace wrapper).
        ORDERS = FakeModel

    result = await service.get_all_custom_tables(FakeEnum)  # type: ignore[arg-type]
    assert result == {"orders"}


# ── upload excel ────────────────────────────────────────────────


@pytest.mark.skipif(
    # Cycle 127: polars not in pyproject deps; defer to integration env.
    not __import__("importlib").util.find_spec("polars"),
    reason="polars not installed (defer to integration env)",
)
@pytest.mark.asyncio
async def test_upload_excel_for_mass_create(service: TechService) -> None:
    from enum import Enum

    import polars as pl

    class FakeModel:
        __tablename__ = "orders"

    class FakeEnum(Enum):
        # Production does ``m.value.__tablename__`` — the enum member's value
        # must be the model object itself (not a SimpleNamespace wrapper).
        ORDERS = FakeModel

    class FakeSchema:
        @classmethod
        def model_validate(cls, data: dict[str, Any]) -> Any:
            return SimpleNamespace(model_dump=lambda: data)

    fake_service = AsyncMock()
    fake_service.request_schema = FakeSchema
    fake_service.get_or_add.return_value = {"id": 1}

    with patch(
        "src.backend.services.core.tech.get_service_for_model",
        return_value=fake_service,
    ), patch(
        "polars.read_excel",
        return_value=pl.DataFrame({"name": ["A"], "amount": [10]}),
    ):
        result = await service.upload_excel_for_mass_create(
            b"",
            "ORDERS",
            FakeEnum,  # type: ignore[arg-type]
        )
        assert len(result) == 1
        assert result[0] == {"id": 1}


@pytest.mark.asyncio
async def test_upload_excel_raises_on_unknown_table(service: TechService) -> None:
    class FakeEnum:
        _member_names_ = ["ORDERS"]

    with pytest.raises(ValueError, match="не найдена"):
        await service.upload_excel_for_mass_create(b"", "UNKNOWN", FakeEnum)  # type: ignore[arg-type]


# ── singleton ───────────────────────────────────────────────────


def test_get_tech_service_singleton() -> None:
    s1 = get_tech_service()
    s2 = get_tech_service()
    assert s1 is s2
