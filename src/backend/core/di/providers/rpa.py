"""RPA domain providers — browser pool + desktop-RPA client (ADR-0401).

Single entry point для RPA-runtime, который раньше **не был зарегистрирован
нигде**: DSL-шаги ``browser_launch`` / ``navigate`` / ``click`` (Playwright)
и ``desktop_rpa`` (windows-worker sidecar) искали зависимость только в
``ExecutionContext`` (``context.browser_pool`` / ``context.desktop_rpa_client``)
и в ``context.app_state`` — которого у :class:`ExecutionContext` нет вовсе
(dataclass со ``slots=True``). В результате RPA browser/desktop всегда
заканчивались ``RuntimeError`` (ADR-0369, дефект G12.6).

Контракт:

* :func:`get_browser_pool_provider` — lazy singleton
  :class:`PlaywrightBrowserPool` (браузер поднимается при первом
  ``acquire()``, не при создании пула);
* :func:`get_desktop_rpa_client_provider` — lazy singleton
  :class:`DesktopRpaClient` (HTTP-клиент к windows-worker);
* :func:`set_browser_pool_provider` / :func:`set_desktop_rpa_client_provider` —
  test-инъекция;
* :func:`shutdown_rpa_runtime` — корректное закрытие browser-pool'а
  (вызывается из composition-root shutdown).

Потолок решения: URL windows-worker'а не вынесен в конфиг-модель
(``core/config/services/rpa.py`` — вне зоны кластера), поэтому используется
документированный дефолт :data:`DEFAULT_DESKTOP_WORKER_URL`; переопределение —
через :func:`set_desktop_rpa_client_provider` (например, в composition root
другого деплоя).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "DEFAULT_DESKTOP_WORKER_URL",
    "get_browser_pool_provider",
    "get_desktop_rpa_client_provider",
    "set_browser_pool_provider",
    "set_desktop_rpa_client_provider",
    "shutdown_rpa_runtime",
)

_logger = get_logger("core.di.providers.rpa")

#: Документированный адрес windows-worker sidecar'а (см. docstring
#: ``services/rpa/desktop_rpa_client.py``).
DEFAULT_DESKTOP_WORKER_URL = "http://windows-worker:9001"

#: Test-инъекция зависимостей (приоритетнее lazy-синглтонов).
_overrides: dict[str, Any] = {}

#: Lazy-синглтоны (создаются при первом обращении).
_browser_pool: Any = None
_desktop_client: Any = None


def get_browser_pool_provider() -> Any:
    """Возвращает :class:`PlaywrightBrowserPool` (lazy singleton).

    Пул создаётся лениво: сам браузер поднимается при первом
    ``acquire()`` (``PlaywrightBrowserPool.startup`` идемпотентен), поэтому
    отсутствие playwright/patchright не ломает старт приложения.

    Returns:
        Экземпляр пула либо объект, зарегистрированный через
        :func:`set_browser_pool_provider`.

    """
    if "browser_pool" in _overrides:
        return _overrides["browser_pool"]
    global _browser_pool
    if _browser_pool is None:
        from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool

        _browser_pool = PlaywrightBrowserPool()
        _logger.info(
            "RPA browser pool created (lazy): size=%s", getattr(_browser_pool, "size", "?")
        )
    return _browser_pool


def set_browser_pool_provider(pool: Any) -> None:
    """Test-инъекция browser-pool'а (заглушка в unit-тестах)."""
    _overrides["browser_pool"] = pool


def get_desktop_rpa_client_provider() -> Any:
    """Возвращает :class:`DesktopRpaClient` (lazy singleton).

    Returns:
        Экземпляр клиента либо объект, зарегистрированный через
        :func:`set_desktop_rpa_client_provider`.

    """
    if "desktop_rpa_client" in _overrides:
        return _overrides["desktop_rpa_client"]
    global _desktop_client
    if _desktop_client is None:
        from src.backend.services.rpa.desktop_rpa_client import DesktopRpaClient

        _desktop_client = DesktopRpaClient(DEFAULT_DESKTOP_WORKER_URL)
        _logger.info("RPA desktop client created (lazy)")
    return _desktop_client


def set_desktop_rpa_client_provider(client: Any) -> None:
    """Test-инъекция desktop-RPA клиента (заглушка в unit-тестах)."""
    _overrides["desktop_rpa_client"] = client


async def shutdown_rpa_runtime() -> None:
    """Закрывает RPA-runtime (browser pool) — вызывается на shutdown.

    Best-effort: ошибка закрытия не должна блокировать остальные шаги
    остановки приложения. Идемпотентно (пул не поднят → no-op).

    """
    global _browser_pool
    pool = _overrides.get("browser_pool") or _browser_pool
    if pool is None:
        return
    shutdown = getattr(pool, "shutdown", None)
    if callable(shutdown):
        try:
            await shutdown()
        except Exception as exc:  # noqa: BLE001 — shutdown не должен ронять процесс
            _logger.warning("rpa.browser_pool_shutdown_failed: %s", exc)
    _browser_pool = None
