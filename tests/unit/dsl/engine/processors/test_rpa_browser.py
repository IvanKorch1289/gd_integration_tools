"""Тесты RPA Universal Stage 1 процессоров.

Wave: ``[wave:s8/k3-rpa-universal-stage1]``. Используют AsyncMock для page
(playwright/patchright не запускается); проверяют контракт и обработку
ошибок (exchange.fail) каждого из 8 процессоров.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.rpa_browser import (
    BrowserLaunchProcessor,
    ClickProcessor,
    ExtractProcessor,
    FillProcessor,
    NavigateProcessor,
    PdfProcessor,
    ScreenshotProcessor,
    WaitForProcessor,
)


def _exchange_with_page(page: Any) -> Exchange[Any]:
    ex: Exchange[Any] = Exchange(in_message=Message(body={}, headers={}))
    ex.set_property("rpa.page", page)
    return ex


def _empty_exchange() -> Exchange[Any]:
    return Exchange(in_message=Message(body={}, headers={}))


# ── NavigateProcessor ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_navigate_calls_page_goto() -> None:
    page = AsyncMock()
    proc = NavigateProcessor(url="https://example.com/")
    await proc.process(_exchange_with_page(page), context=MagicMock())

    page.goto.assert_awaited_once_with("https://example.com/")


@pytest.mark.asyncio
async def test_navigate_fails_when_no_page() -> None:
    proc = NavigateProcessor(url="https://example.com/")
    ex = _empty_exchange()
    await proc.process(ex, context=MagicMock())

    assert ex.status == ExchangeStatus.failed
    assert "page не инициализирована" in (ex.error or "")


# ── ClickProcessor ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_click_calls_page_click_with_timeout() -> None:
    page = AsyncMock()
    proc = ClickProcessor(selector="#submit", timeout=5.0)
    await proc.process(_exchange_with_page(page), context=MagicMock())

    page.click.assert_awaited_once_with("#submit", timeout=5000)


@pytest.mark.asyncio
async def test_click_fail_marks_exchange() -> None:
    page = AsyncMock()
    page.click.side_effect = TimeoutError("element not found")
    proc = ClickProcessor(selector="#missing")
    ex = _exchange_with_page(page)
    await proc.process(ex, context=MagicMock())

    assert ex.status == ExchangeStatus.failed


# ── FillProcessor ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fill_calls_page_fill() -> None:
    page = AsyncMock()
    proc = FillProcessor(selector="input[name=q]", value="hello")
    await proc.process(_exchange_with_page(page), context=MagicMock())

    page.fill.assert_awaited_once_with("input[name=q]", "hello")


# ── ExtractProcessor ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_inner_text_to_body_field() -> None:
    page = AsyncMock()
    element = AsyncMock()
    element.inner_text.return_value = "Привет"
    page.query_selector.return_value = element

    proc = ExtractProcessor(selector="#title", to="body.title")
    ex = _exchange_with_page(page)
    await proc.process(ex, context=MagicMock())

    assert ex.in_message.body == {"title": "Привет"}


@pytest.mark.asyncio
async def test_extract_attribute() -> None:
    page = AsyncMock()
    element = AsyncMock()
    element.get_attribute.return_value = "https://x.test"
    page.query_selector.return_value = element

    proc = ExtractProcessor(selector="a", attribute="href", to="property:link")
    ex = _exchange_with_page(page)
    await proc.process(ex, context=MagicMock())

    assert ex.properties["link"] == "https://x.test"


@pytest.mark.asyncio
async def test_extract_missing_element_fails() -> None:
    page = AsyncMock()
    page.query_selector.return_value = None

    proc = ExtractProcessor(selector="#none")
    ex = _exchange_with_page(page)
    await proc.process(ex, context=MagicMock())

    assert ex.status == ExchangeStatus.failed
    assert "не найден" in (ex.error or "")


# ── WaitForProcessor ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wait_for_selector() -> None:
    page = AsyncMock()
    proc = WaitForProcessor(selector="#loaded", timeout=10.0)
    await proc.process(_exchange_with_page(page), context=MagicMock())

    page.wait_for_selector.assert_awaited_once_with("#loaded", timeout=10000)


@pytest.mark.asyncio
async def test_wait_for_load_state_default() -> None:
    page = AsyncMock()
    proc = WaitForProcessor()
    await proc.process(_exchange_with_page(page), context=MagicMock())

    page.wait_for_load_state.assert_awaited_once()


def test_wait_for_invalid_state_raises() -> None:
    with pytest.raises(ValueError):
        WaitForProcessor(state="bogus")


# ── ScreenshotProcessor ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_returns_bytes_to_property() -> None:
    page = AsyncMock()
    page.screenshot.return_value = b"\x89PNG..."

    proc = ScreenshotProcessor(to="property:rpa.screenshot")
    ex = _exchange_with_page(page)
    await proc.process(ex, context=MagicMock())

    assert ex.properties["rpa.screenshot"] == b"\x89PNG..."


# ── PdfProcessor ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_returns_bytes() -> None:
    page = AsyncMock()
    page.pdf.return_value = b"%PDF-1.7..."

    proc = PdfProcessor(to="property:rpa.pdf", landscape=True)
    ex = _exchange_with_page(page)
    await proc.process(ex, context=MagicMock())

    assert ex.properties["rpa.pdf"].startswith(b"%PDF")
    page.pdf.assert_awaited_once()
    kwargs = page.pdf.await_args.kwargs
    assert kwargs["landscape"] is True
    assert kwargs["format"] == "A4"


# ── BrowserLaunchProcessor ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_browser_launch_acquires_context_and_creates_page() -> None:
    """Pool injection через context.browser_pool."""

    page = AsyncMock()
    pooled_ctx = AsyncMock()
    pooled_ctx.new_page.return_value = page

    class _FakePool:
        def acquire(self):  # noqa: ANN001
            class _CM:
                async def __aenter__(self_inner):
                    return pooled_ctx

                async def __aexit__(self_inner, *args):
                    return None

            return _CM()

    fake_context = MagicMock()
    fake_context.browser_pool = _FakePool()

    proc = BrowserLaunchProcessor(url="https://example.com/")
    ex = _empty_exchange()
    await proc.process(ex, context=fake_context)

    assert ex.properties["rpa.page"] is page
    page.goto.assert_awaited_once_with("https://example.com/")


@pytest.mark.asyncio
async def test_browser_launch_no_pool_fails() -> None:
    proc = BrowserLaunchProcessor()
    fake_context = MagicMock(spec=[])  # no browser_pool / app_state
    ex = _empty_exchange()
    await proc.process(ex, context=fake_context)

    assert ex.status == ExchangeStatus.failed
    assert "PlaywrightBrowserPool" in (ex.error or "")
