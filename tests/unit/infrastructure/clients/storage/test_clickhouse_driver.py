"""TDD: единая точка импорта драйвера ``clickhouse_connect`` (Wave 13 Q8).

Пакет ``clickhouse_connect`` не объявлен ни в ``[project].dependencies``, ни в
одном extra. Helper закрывает оба режима:

* ``required=True``  → доменное исключение с указанием пакета и extra
  (fail-loud: потеря audit-событий / записи истории недопустима);
* ``required=False`` → ``None`` + WARNING в лог (деградация для UI).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.clients.storage import clickhouse_driver
from src.backend.infrastructure.clients.storage.clickhouse_driver import (
    CLICKHOUSE_DRIVER_EXTRA,
    CLICKHOUSE_DRIVER_PACKAGE,
    ClickHouseDriverError,
    create_clickhouse_async_client,
    import_clickhouse_driver,
)

REPO_ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture
def driver_absent() -> Any:
    """Имитирует отсутствие пакета ``clickhouse_connect`` в окружении."""
    with patch.dict(sys.modules, {"clickhouse_connect": None}):
        yield


def _rendered(call_args: Any) -> str:
    """Разворачивает args-вызов логгера в строку."""
    args = call_args[0]
    if len(args) > 1:
        return str(args[0]) % tuple(args[1:])
    return str(args[0])


class TestImportDriver:
    """Семантика ``required`` в :func:`import_clickhouse_driver`."""

    def test_required_raises_domain_error(self, driver_absent: Any) -> None:
        """``required=True`` → доменное исключение вместо ModuleNotFoundError."""
        with pytest.raises(ClickHouseDriverError) as exc_info:
            import_clickhouse_driver(required=True)
        message = str(exc_info.value)
        assert CLICKHOUSE_DRIVER_PACKAGE in message
        assert CLICKHOUSE_DRIVER_EXTRA in message

    def test_optional_returns_none_and_warns(self, driver_absent: Any) -> None:
        """``required=False`` → ``None`` + WARNING в лог."""
        fake_logger = MagicMock()
        with patch.object(clickhouse_driver, "_logger", fake_logger):
            assert import_clickhouse_driver(required=False) is None
        fake_logger.warning.assert_called_once()
        rendered = _rendered(fake_logger.warning.call_args)
        assert CLICKHOUSE_DRIVER_PACKAGE in rendered
        assert CLICKHOUSE_DRIVER_EXTRA in rendered

    def test_returns_module_when_installed(self) -> None:
        """Пакет установлен → возвращается сам модуль."""
        fake_module = SimpleNamespace(get_async_client=AsyncMock())
        with patch.dict(sys.modules, {"clickhouse_connect": fake_module}):
            assert import_clickhouse_driver(required=True) is fake_module

    def test_error_is_domain_exception(self, driver_absent: Any) -> None:
        """Исключение — доменное (наследует ServiceError), не ImportError."""
        from src.backend.core.errors import ServiceError

        assert issubclass(ClickHouseDriverError, ServiceError)
        with pytest.raises(ServiceError):
            import_clickhouse_driver(required=True)


class TestCreateClient:
    """Семантика :func:`create_clickhouse_async_client`."""

    @pytest.mark.asyncio
    async def test_uses_settings(self) -> None:
        """Клиент создаётся с host/port/database из настроек."""
        fake_client = object()
        fake_module = SimpleNamespace(
            get_async_client=AsyncMock(return_value=fake_client)
        )
        fake_settings = MagicMock()
        fake_settings.clickhouse.host = "ch-host"
        fake_settings.clickhouse.port = 9000
        fake_settings.clickhouse.database = "analytics"
        fake_config = MagicMock()
        fake_config.settings = fake_settings

        with (
            patch.dict(sys.modules, {"clickhouse_connect": fake_module}),
            patch.dict(sys.modules, {"src.backend.core.config": fake_config}),
        ):
            client = await create_clickhouse_async_client(required=True)

        assert client is fake_client
        fake_module.get_async_client.assert_awaited_once_with(
            host="ch-host", port=9000, database="analytics"
        )

    @pytest.mark.asyncio
    async def test_required_raises_when_absent(self, driver_absent: Any) -> None:
        """``required=True`` → доменное исключение (fail-loud)."""
        with pytest.raises(ClickHouseDriverError):
            await create_clickhouse_async_client(required=True)

    @pytest.mark.asyncio
    async def test_optional_returns_none_when_absent(self, driver_absent: Any) -> None:
        """``required=False`` → ``None`` (деградация для дашбордов/админки)."""
        fake_logger = MagicMock()
        with patch.object(clickhouse_driver, "_logger", fake_logger):
            assert await create_clickhouse_async_client(required=False) is None
        fake_logger.warning.assert_called_once()


class TestNoDirectDriverImports:
    """Все прямые импорты драйвера собраны в одном модуле."""

    def test_clickhouse_connect_imported_only_in_helper(self) -> None:
        """В ``src/`` драйвер импортируется только через infrastructure-helper."""
        offenders: list[str] = []
        for py in sorted((REPO_ROOT / "src").rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            if py.name == "clickhouse_driver.py":
                continue
            text = py.read_text(encoding="utf-8")
            if "import clickhouse_connect" in text or "from clickhouse_connect" in text:
                offenders.append(py.relative_to(REPO_ROOT).as_posix())
        assert offenders == []
