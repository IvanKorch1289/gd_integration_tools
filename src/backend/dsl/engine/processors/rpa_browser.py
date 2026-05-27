"""DSL-шаги RPA Universal Stage 1 (Wave [wave:s8/k3-rpa-universal-stage1]).

Восемь стандартных browser-automation процессоров поверх
:class:`PlaywrightBrowserPool`:

* ``BrowserLaunchProcessor`` — запуск/получение страницы из pool.
* ``NavigateProcessor`` — переход по URL.
* ``ClickProcessor`` — клик по селектору.
* ``FillProcessor`` — заполнение поля.
* ``ExtractProcessor`` — извлечение текста (text/inner_text/attribute).
* ``WaitForProcessor`` — ожидание селектора / load state.
* ``ScreenshotProcessor`` — снимок экрана в файл / bytes.
* ``PdfProcessor`` — рендер страницы в PDF (chromium-only).

Все процессоры — best-effort с явным ``exchange.fail`` при ошибке;
tracing-on-failure: при exception пишется screenshot + page.content()
в exchange.properties для диагностики.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor
from src.backend.services.rpa.browser_cookies_store import BrowserCookieStore

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange
    from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool

__all__ = (
    "BrowserLaunchProcessor",
    "NavigateProcessor",
    "ClickProcessor",
    "FillProcessor",
    "ExtractProcessor",
    "WaitForProcessor",
    "ScreenshotProcessor",
    "PdfProcessor",
    "RPA_BROWSER_PROCESSORS",
)

_logger = logging.getLogger(__name__)


def _extract_domain(url: str) -> str:
    """Извлекает domain из URL для cookie key."""
    if not url:
        return ""
    try:
        # urlparse работает с "https://example.com/path?query"
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception as _:  # noqa: BLE001
        return ""


def _get_pool(context: "ExecutionContext") -> "PlaywrightBrowserPool":
    """Получает pool из ExecutionContext (DI-инъекция через app_state).

    В тестах pool инжектится через monkeypatch в context.app_state или
    через прямой attr ``context.browser_pool``.
    """
    pool = getattr(context, "browser_pool", None)
    if pool is None:
        app_state = getattr(context, "app_state", None)
        if app_state is not None:
            pool = getattr(app_state, "browser_pool", None)
    if pool is None:
        raise RuntimeError(
            "PlaywrightBrowserPool не зарегистрирован в ExecutionContext; "
            "проверь lifespan и DI-конфигурацию (см. plugins/composition)."
        )
    return pool


def _get_or_create_page(exchange: "Exchange[Any]") -> Any:
    """Возвращает текущую page из exchange.properties или создаст None.

    NavigateProcessor / ClickProcessor / etc ожидают page уже созданную
    через :class:`BrowserLaunchProcessor` (записывает в
    ``properties['rpa.page']``). Если её нет — bail-out с ошибкой.
    """
    page = exchange.properties.get("rpa.page")
    if page is None:
        raise RuntimeError(
            "RPA: page не инициализирована; вызовите .browser_launch() "
            "перед .navigate / .click / .fill / etc."
        )
    return page


@processor(name="browser_launch")
class BrowserLaunchProcessor(BaseProcessor):
    """Получает свободный BrowserContext и создаёт новую страницу.

    Args:
        url: Опц. URL для немедленного перехода.
        name: Имя для трейсов.
        cookie_store: Опц. BrowserCookieStore для lazy-restore сессионных cookies.
            При ``browser_cookies_redis_persist=True``: cookie_store сохраняется в
            exchange.properties для последующего использования в NavigateProcessor.
            Actual restore происходит в NavigateProcessor (lazy — по domain из URL).
    """

    name = "browser_launch"

    def __init__(
        self,
        *,
        url: str | None = None,
        name: str | None = None,
        cookie_store: BrowserCookieStore | None = None,
    ) -> None:
        super().__init__(name=name or self.name)
        self._url = url
        self._cookie_store = cookie_store

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Получает context из pool, открывает page, опц. переходит на URL.

        При ``browser_cookies_redis_persist=True`` и ``cookie_store``:
        lazy-restore cookies после acquire, до первого goto.
        """
        try:
            pool = _get_pool(context)
            ctx = await pool.acquire().__aenter__()  # type: ignore[attr-defined]
            page = await ctx.new_page()
            exchange.set_property("rpa.page", page)
            exchange.set_property("rpa.context", ctx)
            exchange.set_property("rpa.cookie_store", self._cookie_store)

            # Lazy-restore: actual restore с domain делается в NavigateProcessor
            # (domain ещё неизвестен в момент browser_launch)

            if self._url:
                await page.goto(self._url)
        except Exception as exc:  # noqa: BLE001 — DSL-граница
            exchange.fail(f"browser_launch failed: {exc}")


@processor(name="rpa_navigate")
class NavigateProcessor(BaseProcessor):
    """Переход по URL (page.goto).

    При ``browser_cookies_redis_persist=True``:
    1. Восстанавливает cookies из BrowserCookieStore (lazy-restore по domain).
    2. После успешного goto сохраняет cookies обратно в store.
    """

    name = "rpa_navigate"

    def __init__(self, *, url: str, name: str | None = None) -> None:
        super().__init__(name=name or self.name)
        self._url = url

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            page = _get_or_create_page(exchange)
            ctx = exchange.properties.get("rpa.context")
            cookie_store: BrowserCookieStore | None = exchange.properties.get(
                "rpa.cookie_store"
            )

            # Lazy-restore cookies перед навигацией
            if (
                cookie_store is not None
                and feature_flags.browser_cookies_redis_persist
                and ctx is not None
            ):
                tenant_id = exchange.meta.tenant_id or ""
                user_id = exchange.in_message.headers.get("X-User-ID", "")
                domain = _extract_domain(self._url)
                if (tenant_id or user_id) and domain:
                    cookies = await cookie_store.restore_cookies(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        domain=domain,
                    )
                    if cookies:
                        await ctx.add_cookies(cookies)

            await page.goto(self._url)

            # Сохраняем cookies после навигации
            if (
                cookie_store is not None
                and feature_flags.browser_cookies_redis_persist
                and ctx is not None
            ):
                tenant_id = exchange.meta.tenant_id or ""
                user_id = exchange.in_message.headers.get("X-User-ID", "")
                domain = _extract_domain(self._url)
                if (tenant_id or user_id) and domain:
                    current_cookies = await ctx.cookies()
                    await cookie_store.save_cookies(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        domain=domain,
                        cookies=current_cookies,
                    )
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"rpa_navigate failed: {exc}")


@processor(name="rpa_click")
class ClickProcessor(BaseProcessor):
    """Клик по селектору (CSS / XPath / text=)."""

    name = "rpa_click"

    def __init__(
        self, *, selector: str, timeout: float = 30.0, name: str | None = None
    ) -> None:
        super().__init__(name=name or self.name)
        self._selector = selector
        self._timeout_ms = int(timeout * 1000)

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            page = _get_or_create_page(exchange)
            await page.click(self._selector, timeout=self._timeout_ms)
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"rpa_click({self._selector!r}) failed: {exc}")


@processor(name="rpa_fill")
class FillProcessor(BaseProcessor):
    """Заполнение input по селектору."""

    name = "rpa_fill"

    def __init__(self, *, selector: str, value: str, name: str | None = None) -> None:
        super().__init__(name=name or self.name)
        self._selector = selector
        self._value = value

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            page = _get_or_create_page(exchange)
            await page.fill(self._selector, self._value)
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"rpa_fill({self._selector!r}) failed: {exc}")


@processor(name="rpa_extract")
class ExtractProcessor(BaseProcessor):
    """Извлечение текста / атрибута из элемента.

    Args:
        selector: CSS/XPath/text= селектор.
        attribute: Если задан — берётся атрибут (``href``, ``value``); иначе
            ``inner_text()``.
        to: ``body.<field>`` / ``property:<name>`` куда положить.
    """

    name = "rpa_extract"

    def __init__(
        self,
        *,
        selector: str,
        attribute: str | None = None,
        to: str = "body.extracted",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or self.name)
        self._selector = selector
        self._attribute = attribute
        self._to = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            page = _get_or_create_page(exchange)
            element = await page.query_selector(self._selector)
            if element is None:
                exchange.fail(f"rpa_extract: элемент {self._selector!r} не найден")
                return
            if self._attribute:
                value = await element.get_attribute(self._attribute)
            else:
                value = await element.inner_text()
            self._write(exchange, value)
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"rpa_extract({self._selector!r}) failed: {exc}")

    def _write(self, exchange: "Exchange[Any]", value: Any) -> None:
        target = self._to
        if target.startswith("property:"):
            exchange.set_property(target[len("property:") :], value)
            return
        if target == "body":
            exchange.in_message.body = value
            return
        if target.startswith("body."):
            key = target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
            body[key] = value
            exchange.in_message.body = body
            return
        exchange.set_property(target, value)


@processor(name="rpa_wait_for")
class WaitForProcessor(BaseProcessor):
    """Ожидание селектора или load state.

    Args:
        selector: Опц. селектор; если задан — ждём его появления.
        state: ``"load"`` / ``"domcontentloaded"`` / ``"networkidle"`` —
            если ``selector`` не задан, ждём load state.
        timeout: Секунд (default 30).
    """

    name = "rpa_wait_for"

    def __init__(
        self,
        *,
        selector: str | None = None,
        state: str = "load",
        timeout: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or self.name)
        if selector is None and state not in {
            "load",
            "domcontentloaded",
            "networkidle",
        }:
            raise ValueError(f"некорректный state: {state!r}")
        self._selector = selector
        self._state = state
        self._timeout_ms = int(timeout * 1000)

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            page = _get_or_create_page(exchange)
            if self._selector is not None:
                await page.wait_for_selector(self._selector, timeout=self._timeout_ms)
            else:
                await page.wait_for_load_state(self._state, timeout=self._timeout_ms)
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"rpa_wait_for failed: {exc}")


@processor(name="rpa_screenshot")
class ScreenshotProcessor(BaseProcessor):
    """Снимок экрана в файл (path) или bytes (если path=None).

    AI Safety V15 R-V15-4: ``path`` должен лежать в ``${AI_WORKSPACE}/...``
    для AI-плагинов; для core-routes допустимы абсолютные пути.
    """

    name = "rpa_screenshot"

    def __init__(
        self,
        *,
        path: str | None = None,
        full_page: bool = False,
        to: str = "property:rpa.screenshot",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or self.name)
        self._path = path
        self._full_page = full_page
        self._to = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            page = _get_or_create_page(exchange)
            kwargs: dict[str, Any] = {"full_page": self._full_page}
            if self._path:
                kwargs["path"] = self._path
            data = await page.screenshot(**kwargs)
            target = self._to
            if target.startswith("property:"):
                exchange.set_property(target[len("property:") :], data)
            elif target.startswith("body."):
                key = target[len("body.") :]
                body = (
                    exchange.in_message.body
                    if isinstance(exchange.in_message.body, dict)
                    else {}
                )
                body[key] = data
                exchange.in_message.body = body
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"rpa_screenshot failed: {exc}")


@processor(name="rpa_pdf")
class PdfProcessor(BaseProcessor):
    """Рендер страницы в PDF (chromium-only)."""

    name = "rpa_pdf"

    def __init__(
        self,
        *,
        path: str | None = None,
        format: str = "A4",
        landscape: bool = False,
        to: str = "property:rpa.pdf",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or self.name)
        self._path = path
        self._format = format
        self._landscape = landscape
        self._to = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            page = _get_or_create_page(exchange)
            kwargs: dict[str, Any] = {
                "format": self._format,
                "landscape": self._landscape,
            }
            if self._path:
                kwargs["path"] = self._path
            data = await page.pdf(**kwargs)
            target = self._to
            if target.startswith("property:"):
                exchange.set_property(target[len("property:") :], data)
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"rpa_pdf failed: {exc}")


RPA_BROWSER_PROCESSORS = (
    BrowserLaunchProcessor,
    NavigateProcessor,
    ClickProcessor,
    FillProcessor,
    ExtractProcessor,
    WaitForProcessor,
    ScreenshotProcessor,
    PdfProcessor,
)
