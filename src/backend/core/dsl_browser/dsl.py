"""Typed DSL wrapper for Playwright Page (P4.18).

Проблема:
    ``playwright.click("#submit-btn")`` — fragile и неуправляемый:
    - Селекторы хардкодятся в Python (нет единого источника правды).
    - Одинаковый код повторяется в каждом RPA-сценарии.
    - Нет retry/screenshot capture из коробки.
    - Нет recording/telemetry событий.

Решение:
    ``BrowserDSL`` — typed layer поверх Playwright Page:

    1. ``SemanticAction`` enum — типизированный действия (LOGIN, SUBMIT, ...).
    2. ``SelectorStrategy`` enum — chain TEST_ID → ARIA → TEXT → CSS.
    3. ``BrowserConfig`` — retries/timeout/screenshot_dir.
    4. ``StepResult`` — success/screenshot_path/error/duration_ms.
    5. ``BrowserDSL`` — ``goto()``/``click()``/``fill()``/``wait_for()``/``screenshot()``.

Использование::

    from src.backend.core.dsl_browser import (
        BrowserDSL, BrowserConfig, SemanticAction,
    )

    page = await browser.new_page()
    dsl = BrowserDSL(page, BrowserConfig(retries=3))

    await dsl.goto("https://example.com/login")
    await dsl.fill(SemanticAction.LOGIN, "username", "alice")
    await dsl.fill(SemanticAction.LOGIN, "password", "secret")
    await dsl.click(SemanticAction.SUBMIT, "login-form")
    await dsl.screenshot("after_login")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = (
    "BrowserConfig",
    "BrowserDSL",
    "SelectorStrategy",
    "SemanticAction",
    "StepResult",
)


class SemanticAction(str, Enum):
    """Typed RPA action vocabulary.

    Используется как первая координата selector resolution — каждое
    действие может иметь свой набор preferred strategies.
    """

    NAVIGATE = "navigate"
    LOGIN = "login"
    LOGOUT = "logout"
    SUBMIT = "submit"
    CANCEL = "cancel"
    CONFIRM = "confirm"
    SEARCH = "search"
    SAVE = "save"
    EDIT = "edit"
    DELETE = "delete"
    CUSTOM = "custom"


class SelectorStrategy(str, Enum):
    """Selector resolution strategies (priority-ordered)."""

    TEST_ID = "test-id"  # [data-testid="value"]
    ARIA = "aria"  # [aria-label="value"]
    ROLE = "role"  # role=button[name="value"]
    TEXT = "text"  # text="value"
    CSS = "css"  # raw CSS as fallback


@dataclass(slots=True)
class BrowserConfig:
    """Configuration для ``BrowserDSL``.

    Attributes:
        timeout_ms: Page operation timeout (milliseconds).
        retries: Количество retry-попыток при ошибке.
        retry_delay_ms: Задержка между retries (milliseconds).
        screenshot_dir: Директория для screenshot'ов (создаётся при необходимости).
        strategies: Priority chain для selector resolution.
        screenshot_on_error: Делать ли screenshot при ошибке step.
        step_delay_ms: Минимальная задержка между step'ами (anti-ban heuristic).
    """

    timeout_ms: int = 30_000
    retries: int = 3
    retry_delay_ms: int = 100
    screenshot_dir: str = "/tmp/dsl_browser"  # noqa: S108 — default tempdir override
    strategies: tuple[SelectorStrategy, ...] = (
        SelectorStrategy.TEST_ID,
        SelectorStrategy.ARIA,
        SelectorStrategy.TEXT,
        SelectorStrategy.CSS,
    )
    screenshot_on_error: bool = True
    step_delay_ms: int = 0


@dataclass(slots=True)
class StepResult:
    """Result of a single DSL step.

    Attributes:
        action: Какое ``SemanticAction`` было выполнено.
        selector_value: Значение, переданное для resolution.
        success: True если step выполнился без ошибки.
        duration_ms: Время выполнения step (включая retries).
        screenshot_path: Путь к screenshot (если делался).
        error: Текст ошибки (``None`` если success).
        retries: Количество использованных retry-попыток.
        resolved_selector: Финальный CSS-селектор, который сработал.
    """

    action: SemanticAction
    selector_value: str
    success: bool
    duration_ms: float = 0.0
    screenshot_path: str | None = None
    error: str | None = None
    retries: int = 0
    resolved_selector: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dict для telemetry/recording."""
        return {
            "action": self.action.value,
            "selector_value": self.selector_value,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "screenshot_path": self.screenshot_path,
            "error": self.error,
            "retries": self.retries,
            "resolved_selector": self.resolved_selector,
        }


@runtime_checkable
class PlaywrightPageProtocol(Protocol):
    """Minimal Protocol для Playwright Page.

    Определяет только методы, которые мы используем. Позволяет:
    - Type-check DSL с mock page в тестах.
    - Не зависеть от playwright в runtime (lazy import).
    """

    async def goto(self, url: str, **kwargs: Any) -> Any: ...

    async def click(self, selector: str, **kwargs: Any) -> None: ...

    async def fill(self, selector: str, value: str, **kwargs: Any) -> None: ...

    async def wait_for_selector(self, selector: str, **kwargs: Any) -> Any: ...

    async def screenshot(self, path: str | None = None, **kwargs: Any) -> bytes: ...


class BrowserDSL:
    """Typed DSL wrapper поверх Playwright Page.

    Attributes:
        page: Playwright Page или любой объект, реализующий ``PlaywrightPageProtocol``.
        config: ``BrowserConfig`` с retries/timeout/screenshot_dir.

    Methods:
        goto(): Navigate to URL.
        click(): Click element using selector strategy chain.
        fill(): Fill input field.
        wait_for(): Wait for element to be visible.
        screenshot(): Take screenshot.
        build_selector(): Build selector string from strategy + value.
        history(): Read-only history of executed steps.
    """

    def __init__(self, page: Any, config: BrowserConfig | None = None) -> None:
        self._page = page
        self._config = config or BrowserConfig()
        self._history: list[StepResult] = []
        # Lazy-create screenshot dir.
        try:
            os.makedirs(self._config.screenshot_dir, exist_ok=True)
        except OSError:
            # Read-only FS or permission denied — keep going.
            logger.warning(
                "Cannot create screenshot dir %s", self._config.screenshot_dir
            )

    @property
    def page(self) -> Any:
        return self._page

    @property
    def config(self) -> BrowserConfig:
        return self._config

    def history(self) -> tuple[StepResult, ...]:
        """Read-only history of executed steps."""
        return tuple(self._history)

    def build_selector(self, value: str, strategy: SelectorStrategy) -> str:
        """Build selector string для конкретной strategy.

        Args:
            value: Значение, переданное в DSL step.
            strategy: ``SelectorStrategy`` для построения селектора.

        Returns:
            CSS или Playwright selector string.

        Examples:
            >>> dsl.build_selector("submit", SelectorStrategy.TEST_ID)
            '[data-testid="submit"]'
            >>> dsl.build_selector("Submit", SelectorStrategy.ROLE)
            'role=button[name="Submit"]'
        """
        if strategy == SelectorStrategy.TEST_ID:
            return f'[data-testid="{value}"]'
        if strategy == SelectorStrategy.ARIA:
            return f'[aria-label="{value}"]'
        if strategy == SelectorStrategy.ROLE:
            # Default role=button — caller может переопределить через raw CSS.
            return f'role=button[name="{value}"]'
        if strategy == SelectorStrategy.TEXT:
            return f'text="{value}"'
        # CSS — return as-is.
        return value

    async def goto(self, url: str) -> StepResult:
        """Navigate page to URL.

        Args:
            url: Absolute или relative URL. Передаётся в page.goto() напрямую —
                selector strategy chain применяется только к DOM-операциям.

        Returns:
            :class:`StepResult` с success=True если page loaded без timeout.
        """
        # monotonic() — robust to wall-clock changes (NTP, DST).
        start = time.monotonic()
        attempts = 0
        last_error: str | None = None
        for attempt in range(self._config.retries + 1):
            attempts = attempt
            try:
                await self._page.goto(url, timeout=self._config.timeout_ms)
                duration = (time.monotonic() - start) * 1000
                result = StepResult(
                    action=SemanticAction.NAVIGATE,
                    selector_value=url,
                    success=True,
                    duration_ms=duration,
                    retries=attempt,
                    resolved_selector=url,
                )
                self._history.append(result)
                return result
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self._config.retries:
                    await asyncio.sleep(self._config.retry_delay_ms / 1000)
        # All retries exhausted.
        duration = (time.monotonic() - start) * 1000
        screenshot_path: str | None = None
        if self._config.screenshot_on_error:
            # Wall-clock для filename uniqueness (intuitive timestamp).
            error_name = f"error_navigate_{int(time.time() * 1000)}"
            screenshot_path = os.path.join(
                self._config.screenshot_dir, f"{error_name}.png"
            )
            try:
                await self._page.screenshot(path=screenshot_path)
            except Exception as ss_exc:
                logger.warning("Screenshot on error failed: %s", ss_exc)
                screenshot_path = None
        result = StepResult(
            action=SemanticAction.NAVIGATE,
            selector_value=url,
            success=False,
            duration_ms=duration,
            screenshot_path=screenshot_path,
            error=last_error,
            retries=attempts,
            resolved_selector=url,
        )
        self._history.append(result)
        return result

    async def click(self, action: SemanticAction, selector_value: str) -> StepResult:
        """Click element using selector strategy chain.

        Args:
            action: ``SemanticAction`` (LOGIN, SUBMIT, ...).
            selector_value: Значение для resolution.

        Returns:
            :class:`StepResult` — success=True если хотя бы одна strategy сработала.
        """
        return await self._execute_step(
            action=action,
            selector_value=selector_value,
            op=lambda sel: self._page.click(sel, timeout=self._config.timeout_ms),
        )

    async def fill(
        self, action: SemanticAction, selector_value: str, text: str
    ) -> StepResult:
        """Fill input field with text.

        Args:
            action: ``SemanticAction``.
            selector_value: Значение для resolution.
            text: Текст для ввода в поле.

        Returns:
            :class:`StepResult` — success=True если fill сработал.
        """
        return await self._execute_step(
            action=action,
            selector_value=selector_value,
            op=lambda sel: self._page.fill(sel, text, timeout=self._config.timeout_ms),
        )

    async def wait_for(self, action: SemanticAction, selector_value: str) -> StepResult:
        """Wait for element matching selector chain to appear.

        Args:
            action: ``SemanticAction``.
            selector_value: Значение для resolution.

        Returns:
            :class:`StepResult` — success=True если element visible.
        """
        return await self._execute_step(
            action=action,
            selector_value=selector_value,
            op=lambda sel: self._page.wait_for_selector(
                sel, timeout=self._config.timeout_ms
            ),
        )

    async def screenshot(self, name: str) -> StepResult:
        """Take screenshot и сохранить в screenshot_dir.

        Args:
            name: Имя файла (без расширения).

        Returns:
            :class:`StepResult` с ``screenshot_path`` заполненным путём.
        """
        start = time.monotonic()
        action = SemanticAction.CUSTOM
        path = os.path.join(self._config.screenshot_dir, f"{name}.png")
        try:
            await self._page.screenshot(path=path)
            result = StepResult(
                action=action,
                selector_value=name,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                screenshot_path=path,
            )
        except Exception as exc:
            result = StepResult(
                action=action,
                selector_value=name,
                success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
        self._history.append(result)
        return result

    async def _execute_step(
        self, action: SemanticAction, selector_value: str, op: Any
    ) -> StepResult:
        """Execute step with retry + strategy chain + screenshot-on-error.

        Args:
            action: ``SemanticAction``.
            selector_value: Значение для resolution.
            op: Callable(selector) -> coroutine — page operation.

        Returns:
            :class:`StepResult` с финальным статусом.
        """
        start = time.monotonic()
        last_error: str | None = None
        resolved: str | None = None
        attempts = 0

        for attempt in range(self._config.retries + 1):
            attempts = attempt
            for strategy in self._config.strategies:
                selector = self.build_selector(selector_value, strategy)
                try:
                    await op(selector)
                    # Success.
                    duration = (time.monotonic() - start) * 1000
                    if self._config.step_delay_ms > 0:
                        await asyncio.sleep(self._config.step_delay_ms / 1000)
                    result = StepResult(
                        action=action,
                        selector_value=selector_value,
                        success=True,
                        duration_ms=duration,
                        retries=attempt,
                        resolved_selector=selector,
                    )
                    self._history.append(result)
                    return result
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.debug(
                        "DSL step failed (attempt=%d, strategy=%s, value=%s): %s",
                        attempt,
                        strategy.value,
                        selector_value,
                        last_error,
                    )
                    # Continue to next strategy.
                    continue
            # All strategies failed this attempt → wait + retry.
            if attempt < self._config.retries:
                await asyncio.sleep(self._config.retry_delay_ms / 1000)

        # All retries exhausted.
        duration = (time.monotonic() - start) * 1000
        screenshot_path: str | None = None
        if self._config.screenshot_on_error:
            # Wall-clock для filename uniqueness.
            error_name = f"error_{action.value}_{int(time.time() * 1000)}"
            screenshot_path = os.path.join(
                self._config.screenshot_dir, f"{error_name}.png"
            )
            try:
                await self._page.screenshot(path=screenshot_path)
            except Exception as ss_exc:
                logger.warning("Screenshot on error failed: %s", ss_exc)
                screenshot_path = None

        result = StepResult(
            action=action,
            selector_value=selector_value,
            success=False,
            duration_ms=duration,
            screenshot_path=screenshot_path,
            error=last_error,
            retries=attempts,
            resolved_selector=resolved,
        )
        self._history.append(result)
        return result
