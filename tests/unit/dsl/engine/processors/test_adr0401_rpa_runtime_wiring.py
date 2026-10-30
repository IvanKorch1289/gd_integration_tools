"""ADR-0401 — RPA-runtime (browser pool / desktop client) зарегистрирован в DI.

До фикса ``browser_pool`` и ``desktop_rpa_client`` **не были зарегистрированы
ни в plugins/, ни в core/di/** (grep — 0 совпадений). DSL-шаги искали их
только в ``ExecutionContext`` — а у него (dataclass со ``slots=True``) нет ни
одного из этих атрибутов, как и ``app_state``. В результате RPA browser/desktop
всегда заканчивались ``RuntimeError`` (ADR-0369, дефект G12.6).

Тесты покрывают:

* DI-провайдеры RPA (``core/di/providers/rpa.py``) — singleton + инъекция;
* разрешение зависимости в процессорах через DI (без пула в контексте);
* корректный shutdown browser-pool'а.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.di.providers import rpa as rpa_providers
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.desktop_rpa import DesktopRpaProcessor
from src.backend.dsl.engine.processors.rpa_browser import BrowserLaunchProcessor

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_rpa_providers() -> Any:
    """Сбрасывает состояние RPA-провайдеров после теста."""
    saved_overrides = dict(rpa_providers._overrides)
    saved_pool = rpa_providers._browser_pool
    saved_client = rpa_providers._desktop_client
    yield
    rpa_providers._overrides.clear()
    rpa_providers._overrides.update(saved_overrides)
    rpa_providers._browser_pool = saved_pool
    rpa_providers._desktop_client = saved_client


class _FakePool:
    """Заглушка browser-pool'а (context manager с ``new_page``)."""

    def __init__(self) -> None:
        self.page = AsyncMock()
        self.context = AsyncMock()
        self.context.new_page.return_value = self.page
        self.shutdown_calls = 0

    def acquire(self) -> Any:
        """Возвращает async context manager с browser-context'ом."""

        class _CM:
            async def __aenter__(self_inner: Any) -> Any:
                return self_outer.context

            async def __aexit__(self_inner: Any, *args: Any) -> None:
                return None

        self_outer = self
        return _CM()

    async def shutdown(self) -> None:
        """Считает вызовы shutdown."""
        self.shutdown_calls += 1


def _empty_exchange() -> Exchange[Any]:
    """Пустой exchange для процессоров."""
    return Exchange(in_message=Message(body={}, headers={}))


# ── DI-провайдеры ────────────────────────────────────────────────────────


def test_browser_pool_provider_is_lazy_singleton() -> None:
    """Провайдер отдаёт один и тот же экземпляр пула."""
    first = rpa_providers.get_browser_pool_provider()
    second = rpa_providers.get_browser_pool_provider()

    assert first is not None
    assert first is second


def test_browser_pool_provider_uses_override() -> None:
    """Зарегистрированный пул используется провайдером (test-инъекция)."""
    stub = _FakePool()
    rpa_providers.set_browser_pool_provider(stub)

    assert rpa_providers.get_browser_pool_provider() is stub


def test_desktop_client_provider_uses_override() -> None:
    """Зарегистрированный desktop-клиент используется провайдером."""
    stub = AsyncMock()
    rpa_providers.set_desktop_rpa_client_provider(stub)

    assert rpa_providers.get_desktop_rpa_client_provider() is stub


# ── процессоры разрешают зависимость через DI ────────────────────────────


@pytest.mark.asyncio
async def test_browser_launch_resolves_pool_from_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без пула в контексте процессор берёт pool из DI-провайдера."""
    monkeypatch.setattr(
        BrowserLaunchProcessor, "auth_check", AsyncMock(return_value=True)
    )
    stub = _FakePool()
    rpa_providers.set_browser_pool_provider(stub)

    exchange = _empty_exchange()
    await BrowserLaunchProcessor().process(exchange, context=MagicMock(spec=[]))

    assert exchange.status != ExchangeStatus.failed
    assert exchange.properties["rpa.page"] is stub.page


@pytest.mark.asyncio
async def test_desktop_rpa_resolves_client_from_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без клиента в контексте процессор берёт client из DI-провайдера."""
    monkeypatch.setattr(
        DesktopRpaProcessor, "auth_check", AsyncMock(return_value=True)
    )
    client = AsyncMock()
    client.execute.return_value = {"ok": True}
    rpa_providers.set_desktop_rpa_client_provider(client)

    exchange = _empty_exchange()
    await DesktopRpaProcessor(app="app.exe", action="click").process(
        exchange, context=MagicMock(spec=[])
    )

    assert exchange.status != ExchangeStatus.failed
    client.execute.assert_awaited_once()


# ── shutdown ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shutdown_rpa_runtime_closes_pool() -> None:
    """Shutdown корректно закрывает browser-pool."""
    stub = _FakePool()
    rpa_providers.set_browser_pool_provider(stub)

    await rpa_providers.shutdown_rpa_runtime()

    assert stub.shutdown_calls == 1
