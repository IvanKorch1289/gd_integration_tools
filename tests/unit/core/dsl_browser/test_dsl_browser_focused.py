"""Focused tests for ``core.dsl_browser`` (P4.18)."""

from __future__ import annotations

import asyncio
import os

import pytest

from src.backend.core.dsl_browser import (
    BrowserConfig,
    BrowserDSL,
    SelectorStrategy,
    SemanticAction,
    StepResult,
)


class MockPage:
    """Mock Playwright Page для тестов.

    Реализует :class:`PlaywrightPageProtocol`. ``fail_until_attempt``
    позволяет симулировать flakiness: первые N attempts бросают
    exception, дальше — success.
    """

    def __init__(
        self,
        fail_until_attempt: int = 0,
        strategy_selector_map: dict[str, str] | None = None,
    ) -> None:
        self._attempt = 0
        self._fail_until_attempt = fail_until_attempt
        self._strategy_selector_map = strategy_selector_map or {}
        self._screenshots: list[str] = []
        self._clicks: list[str] = []
        self._fills: list[tuple[str, str]] = []
        self._got_urls: list[str] = []
        self._waits: list[str] = []

    async def goto(self, url: str, **kwargs: object) -> None:
        self._attempt += 1
        if self._attempt <= self._fail_until_attempt:
            raise RuntimeError(f"goto failed (attempt {self._attempt})")
        self._got_urls.append(url)

    async def click(self, selector: str, **kwargs: object) -> None:
        self._attempt += 1
        # If this selector is in fail-map, raise.
        if selector in self._strategy_selector_map:
            # Treat the value as the desired success selector — skip the rest.
            self._clicks.append(selector)
            return
        if self._attempt <= self._fail_until_attempt:
            raise RuntimeError(f"click failed on {selector}")

    async def fill(self, selector: str, value: str, **kwargs: object) -> None:
        self._fills.append((selector, value))

    async def wait_for_selector(self, selector: str, **kwargs: object) -> None:
        self._waits.append(selector)

    async def screenshot(self, path: str | None = None, **kwargs: object) -> bytes:
        if path is not None:
            # Write a real file so os.path.isfile() works in tests.
            try:
                with open(path, "wb") as f:
                    f.write(b"png")
            except OSError:
                pass
            self._screenshots.append(path)
        return b"png"


class TestSemanticAction:
    def test_values(self) -> None:
        assert SemanticAction.LOGIN.value == "login"
        assert SemanticAction.SUBMIT.value == "submit"
        assert SemanticAction.NAVIGATE.value == "navigate"

    def test_subclass_of_str(self) -> None:
        # str subclass enables JSON serialization without custom encoder.
        assert isinstance(SemanticAction.LOGIN, str)


class TestSelectorStrategy:
    def test_values(self) -> None:
        assert SelectorStrategy.TEST_ID.value == "test-id"
        assert SelectorStrategy.ARIA.value == "aria"
        assert SelectorStrategy.TEXT.value == "text"
        assert SelectorStrategy.CSS.value == "css"


class TestBrowserConfig:
    def test_defaults(self) -> None:
        c = BrowserConfig()
        assert c.timeout_ms == 30_000
        assert c.retries == 3
        assert c.retry_delay_ms == 100
        assert c.screenshot_on_error is True
        assert len(c.strategies) == 4

    def test_custom(self, tmp_path: object) -> None:
        c = BrowserConfig(retries=5, timeout_ms=5_000, screenshot_dir=str(tmp_path))
        assert c.retries == 5
        assert c.timeout_ms == 5_000


class TestStepResult:
    def test_defaults(self) -> None:
        r = StepResult(action=SemanticAction.LOGIN, selector_value="user", success=True)
        assert r.duration_ms == 0.0
        assert r.error is None
        assert r.retries == 0
        assert r.screenshot_path is None
        assert r.resolved_selector is None

    def test_to_dict(self) -> None:
        r = StepResult(
            action=SemanticAction.SUBMIT,
            selector_value="btn",
            success=False,
            error="timeout",
            retries=2,
            resolved_selector='[data-testid="btn"]',
        )
        d = r.to_dict()
        assert d["action"] == "submit"
        assert d["success"] is False
        assert d["error"] == "timeout"
        assert d["retries"] == 2
        assert d["resolved_selector"] == '[data-testid="btn"]'


class TestBuildSelector:
    def test_test_id(self) -> None:
        dsl = BrowserDSL(MockPage(), BrowserConfig(screenshot_dir="/tmp/_t"))
        assert (
            dsl.build_selector("submit", SelectorStrategy.TEST_ID)
            == '[data-testid="submit"]'
        )

    def test_aria(self) -> None:
        dsl = BrowserDSL(MockPage(), BrowserConfig(screenshot_dir="/tmp/_t"))
        assert (
            dsl.build_selector("Submit", SelectorStrategy.ARIA)
            == '[aria-label="Submit"]'
        )

    def test_role(self) -> None:
        dsl = BrowserDSL(MockPage(), BrowserConfig(screenshot_dir="/tmp/_t"))
        assert (
            dsl.build_selector("Submit", SelectorStrategy.ROLE)
            == 'role=button[name="Submit"]'
        )

    def test_text(self) -> None:
        dsl = BrowserDSL(MockPage(), BrowserConfig(screenshot_dir="/tmp/_t"))
        assert dsl.build_selector("Submit", SelectorStrategy.TEXT) == 'text="Submit"'

    def test_css_raw(self) -> None:
        dsl = BrowserDSL(MockPage(), BrowserConfig(screenshot_dir="/tmp/_t"))
        assert dsl.build_selector("#my-btn", SelectorStrategy.CSS) == "#my-btn"


class TestDSLInit:
    def test_init_default_config(self) -> None:
        dsl = BrowserDSL(MockPage())
        assert dsl.config.retries == 3
        assert dsl.history() == ()

    def test_init_custom_config(self) -> None:
        cfg = BrowserConfig(retries=1, timeout_ms=1000)
        dsl = BrowserDSL(MockPage(), cfg)
        assert dsl.config.retries == 1

    def test_screenshot_dir_created(self, tmp_path: object) -> None:
        BrowserDSL(MockPage(), BrowserConfig(screenshot_dir=str(tmp_path)))
        assert os.path.isdir(str(tmp_path))


class TestGoto:
    async def test_goto_success(self) -> None:
        page = MockPage()
        dsl = BrowserDSL(page, BrowserConfig(retries=0, screenshot_dir="/tmp/_t"))
        result = await dsl.goto("https://example.com")
        assert result.success is True
        assert result.action == SemanticAction.NAVIGATE
        assert "https://example.com" in page._got_urls

    async def test_goto_failure_with_screenshot(self, tmp_path: object) -> None:
        page = MockPage(fail_until_attempt=99)
        cfg = BrowserConfig(retries=1, retry_delay_ms=0, screenshot_dir=str(tmp_path))
        dsl = BrowserDSL(page, cfg)
        result = await dsl.goto("https://broken")
        assert result.success is False
        assert result.error is not None
        assert "RuntimeError" in result.error
        assert result.screenshot_path is not None
        assert os.path.isfile(result.screenshot_path)


class TestClickWithStrategyChain:
    async def test_first_strategy_succeeds(self, tmp_path: object) -> None:
        page = MockPage()
        # Strategy chain: TEST_ID → ARIA → TEXT → CSS.
        # TEST_ID selector [data-testid="submit"] → first call succeeds.
        dsl = BrowserDSL(page, BrowserConfig(retries=0, screenshot_dir=str(tmp_path)))
        result = await dsl.click(SemanticAction.SUBMIT, "submit")
        assert result.success is True
        assert result.resolved_selector == '[data-testid="submit"]'
        assert result.retries == 0

    async def test_retry_then_success(self, tmp_path: object) -> None:
        # Fail first 4 calls (full strategy chain on first attempt),
        # succeed on the 5th call (second attempt, first strategy).
        page2 = _FlakyPage(fail_attempts=4)
        dsl = BrowserDSL(
            page2,
            BrowserConfig(retries=2, retry_delay_ms=0, screenshot_dir=str(tmp_path)),
        )
        result = await dsl.click(SemanticAction.SUBMIT, "submit")
        assert result.success is True
        assert result.retries >= 1
        assert result.resolved_selector == '[data-testid="submit"]'


class TestFill:
    async def test_fill_success(self, tmp_path: object) -> None:
        page = MockPage()
        dsl = BrowserDSL(page, BrowserConfig(retries=0, screenshot_dir=str(tmp_path)))
        result = await dsl.fill(SemanticAction.LOGIN, "username", "alice")
        assert result.success is True
        assert result.action == SemanticAction.LOGIN
        assert any(
            sel.endswith('[data-testid="username"]') and val == "alice"
            for sel, val in page._fills
        )


class TestWaitFor:
    async def test_wait_for_success(self, tmp_path: object) -> None:
        page = MockPage()
        dsl = BrowserDSL(page, BrowserConfig(retries=0, screenshot_dir=str(tmp_path)))
        result = await dsl.wait_for(SemanticAction.SEARCH, "search-input")
        assert result.success is True
        assert result.action == SemanticAction.SEARCH
        assert '[data-testid="search-input"]' in page._waits


class TestScreenshot:
    async def test_screenshot_success(self, tmp_path: object) -> None:
        page = MockPage()
        dsl = BrowserDSL(page, BrowserConfig(screenshot_dir=str(tmp_path)))
        result = await dsl.screenshot("after_login")
        assert result.success is True
        assert result.screenshot_path == os.path.join(str(tmp_path), "after_login.png")
        # MockPage stores full path, so check basename presence.
        assert any(s.endswith("after_login.png") for s in page._screenshots)

    async def test_screenshot_failure(self) -> None:
        page = _BrokenScreenshotPage()
        dsl = BrowserDSL(page, BrowserConfig(screenshot_dir="/tmp/_t"))
        result = await dsl.screenshot("will_fail")
        assert result.success is False
        assert "RuntimeError" in (result.error or "")


class TestHistory:
    async def test_history_records(self, tmp_path: object) -> None:
        page = MockPage()
        dsl = BrowserDSL(page, BrowserConfig(retries=0, screenshot_dir=str(tmp_path)))
        await dsl.goto("https://example.com")
        await dsl.fill(SemanticAction.LOGIN, "u", "alice")
        await dsl.click(SemanticAction.SUBMIT, "btn")
        await dsl.screenshot("done")
        history = dsl.history()
        assert len(history) == 4
        assert history[0].action == SemanticAction.NAVIGATE
        assert history[1].action == SemanticAction.LOGIN
        assert history[2].action == SemanticAction.SUBMIT
        assert history[3].action == SemanticAction.CUSTOM

    async def test_history_immutable(self, tmp_path: object) -> None:
        page = MockPage()
        dsl = BrowserDSL(page, BrowserConfig(screenshot_dir=str(tmp_path)))
        h = dsl.history()
        assert isinstance(h, tuple)
        # Tuple is immutable.
        with pytest.raises((AttributeError, TypeError)):
            h[0] = None  # type: ignore[index]


class TestRetryExhausted:
    async def test_all_retries_fail_with_screenshot(self, tmp_path: object) -> None:
        page = _FlakyPage(fail_attempts=99)  # always fail
        dsl = BrowserDSL(
            page,
            BrowserConfig(retries=2, retry_delay_ms=0, screenshot_dir=str(tmp_path)),
        )
        result = await dsl.click(SemanticAction.SUBMIT, "btn")
        assert result.success is False
        assert result.retries == 2
        assert result.screenshot_path is not None
        assert os.path.isfile(result.screenshot_path)


class TestCustomStrategies:
    async def test_single_strategy_chain(self, tmp_path: object) -> None:
        page = MockPage()
        # Only TEST_ID.
        cfg = BrowserConfig(
            retries=0,
            strategies=(SelectorStrategy.TEST_ID,),
            screenshot_dir=str(tmp_path),
        )
        dsl = BrowserDSL(page, cfg)
        result = await dsl.click(SemanticAction.SUBMIT, "btn")
        assert result.success is True
        assert result.resolved_selector == '[data-testid="btn"]'


# ---- Helpers ----------------------------------------------------------------


class _FlakyPage:
    """Page that fails first N attempts and then succeeds.

    Used для testing retry logic. Tracks attempts across all operations.
    """

    def __init__(self, fail_attempts: int) -> None:
        self._attempt = 0
        self._fail_attempts = fail_attempts
        self._got_urls: list[str] = []
        self._clicks: list[str] = []
        self._fills: list[tuple[str, str]] = []
        self._screenshots: list[str] = []

    async def goto(self, url: str, **kwargs: object) -> None:
        self._attempt += 1
        if self._attempt <= self._fail_attempts:
            raise RuntimeError(f"goto fail {self._attempt}")
        self._got_urls.append(url)

    async def click(self, selector: str, **kwargs: object) -> None:
        self._attempt += 1
        if self._attempt <= self._fail_attempts:
            raise RuntimeError(f"click fail {self._attempt}")
        self._clicks.append(selector)

    async def fill(self, selector: str, value: str, **kwargs: object) -> None:
        self._attempt += 1
        if self._attempt <= self._fail_attempts:
            raise RuntimeError(f"fill fail {self._attempt}")
        self._fills.append((selector, value))

    async def wait_for_selector(self, selector: str, **kwargs: object) -> None:
        await asyncio.sleep(0)

    async def screenshot(self, path: str | None = None, **kwargs: object) -> bytes:
        if path is not None:
            # Write a real file so os.path.isfile() works in tests.
            try:
                with open(path, "wb") as f:
                    f.write(b"png")
            except OSError:
                pass
            self._screenshots.append(path)
        return b"png"


class _BrokenScreenshotPage:
    """Page that raises on screenshot calls."""

    async def goto(self, url: str, **kwargs: object) -> None:
        pass

    async def click(self, selector: str, **kwargs: object) -> None:
        pass

    async def fill(self, selector: str, value: str, **kwargs: object) -> None:
        pass

    async def wait_for_selector(self, selector: str, **kwargs: object) -> None:
        pass

    async def screenshot(self, path: str | None = None, **kwargs: object) -> bytes:
        raise RuntimeError("screenshot broken")
