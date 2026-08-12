"""Тесты RPA Universal Stage 1 процессоров.

Wave: ``[wave:s8/k3-rpa-universal-stage1]``. Используют AsyncMock для page
(playwright/patchright не запускается); проверяют контракт и обработку
ошибок (exchange.fail) каждого из 8 процессоров.

S202 audit closure (D-4): каждый процессор имеет ``required_capability``
в формате ``rpa.browser.<verb>`` (per ``docs/rpa/RPA_GUIDE.md`` vocabulary).
Capability-facade stub возвращает denied в unit-тестах, поэтому
``auth_check`` подменяется на no-op через ``_bypass_auth_check`` fixture.
Round-trip тесты проверяют что ``required_capability`` объявлен и
соответствует documented vocabulary.
"""


from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

# All 8 processors — bypass auth_check in unit tests (S202 audit pattern).
_BYPASS_AUTH_TARGETS = (
    BrowserLaunchProcessor,
    NavigateProcessor,
    ClickProcessor,
    FillProcessor,
    ExtractProcessor,
    WaitForProcessor,
    ScreenshotProcessor,
    PdfProcessor,
)


@pytest.fixture(autouse=True)
def _bypass_auth_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяет ``auth_check`` на no-op для всех 8 процессоров.

    В unit-тестах capability-facade stub возвращает denied (fail-closed),
    поэтому ``auth_check`` patch-ится на ``AsyncMock(return_value=True)``.
    Без bypass каждый тест упал бы с ``exchange.set_error("capability denied")``.
    """
    for proc_cls in _BYPASS_AUTH_TARGETS:
        monkeypatch.setattr(proc_cls, "auth_check", AsyncMock(return_value=True))


def _exchange_with_page(page: Any) -> Exchange[Any]:
    ex: Exchange[Any] = Exchange(in_message=Message(body={}, headers={}))
    ex.set_property("rpa.page", page)
    return ex


def _empty_exchange() -> Exchange[Any]:
    return Exchange(in_message=Message(body={}, headers={}))


# ── required_capability round-trip (S202 audit, D-4 closure) ────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("proc_cls", "expected_capability"),
    [
        (BrowserLaunchProcessor, "rpa.browser.launch"),
        (NavigateProcessor, "rpa.browser.navigate"),
        (ClickProcessor, "rpa.browser.click"),
        (FillProcessor, "rpa.browser.fill"),
        (ExtractProcessor, "rpa.browser.extract"),
        (WaitForProcessor, "rpa.browser.wait"),
        (ScreenshotProcessor, "rpa.browser.screenshot"),
        (PdfProcessor, "rpa.browser.pdf"),
    ],
)
def test_required_capability_matches_vocabulary(
    proc_cls: type, expected_capability: str
) -> None:
    """Round-trip: ``required_capability`` соответствует documented vocabulary."""
    assert proc_cls.required_capability == expected_capability
    assert proc_cls.audit_event == expected_capability


@pytest.mark.asyncio
@pytest.mark.unit
async def test_auth_check_denied_short_circuits_processor() -> None:
    """Если ``auth_check`` denied → processor не выполняет основной код.

    Подменяем ``auth_check`` на ``return_value=False`` через ``patch.object``
    (временно поверх autouse fixture). Когда ``auth_check`` patched — это
    mock, не вызывающий ``exchange.set_error`` / ``exchange.stop()``, поэтому
    проверяем короткое замыкание через ``page.goto.assert_not_awaited()``.
    """
    page = AsyncMock()
    proc = NavigateProcessor(url="https://example.com/")
    ex = _exchange_with_page(page)

    with patch.object(
        NavigateProcessor, "auth_check", new=AsyncMock(return_value=False)
    ):
        await proc.process(ex, context=MagicMock())

    page.goto.assert_not_awaited()


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
        def acquire(self):
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


@pytest.mark.asyncio
async def test_browser_launch_releases_context_via_finalizer() -> None:
    """FIX-C1: semaphore/context освобождается в конце route через finalizer.

    Без finalizer poll_size запусков исчерпали бы semaphore → deadlock.
    """

    page = AsyncMock()
    pooled_ctx = AsyncMock()
    pooled_ctx.new_page.return_value = page

    released = {"count": 0}

    class _FakePool:
        def acquire(self):
            class _CM:
                async def __aenter__(self_inner):
                    return pooled_ctx

                async def __aexit__(self_inner, *args):
                    released["count"] += 1

            return _CM()

    fake_context = MagicMock()
    fake_context.browser_pool = _FakePool()

    proc = BrowserLaunchProcessor(url="https://example.com/")
    ex = _empty_exchange()
    await proc.process(ex, context=fake_context)

    # Контекст удерживается во время route — ещё не освобождён.
    assert released["count"] == 0
    assert ex.properties["rpa.page"] is page

    # execution engine вызывает run_finalizers после прогона processors.
    await ex.run_finalizers()
    assert released["count"] == 1


@pytest.mark.asyncio
async def test_browser_launch_finalizer_releases_on_goto_failure() -> None:
    """Даже при ошибке page.goto finalizer освобождает контекст."""

    page = AsyncMock()
    page.goto.side_effect = RuntimeError("net err")
    pooled_ctx = AsyncMock()
    pooled_ctx.new_page.return_value = page

    released = {"count": 0}

    class _FakePool:
        def acquire(self):
            class _CM:
                async def __aenter__(self_inner):
                    return pooled_ctx

                async def __aexit__(self_inner, *args):
                    released["count"] += 1

            return _CM()

    fake_context = MagicMock()
    fake_context.browser_pool = _FakePool()

    proc = BrowserLaunchProcessor(url="https://example.com/")
    ex = _empty_exchange()
    await proc.process(ex, context=fake_context)

    assert ex.status == ExchangeStatus.failed
    await ex.run_finalizers()
    assert released["count"] == 1
