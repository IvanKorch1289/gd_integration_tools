"""Typed DSL wrapper for Browser RPA (P4.18).

Использование::

    from src.backend.core.dsl_browser import (  # noqa: F401 — re-export
        BrowserDSL, BrowserConfig, SemanticAction, SelectorStrategy, StepResult,
    )

    page = await browser.new_page()
    dsl = BrowserDSL(page, BrowserConfig(retries=3))

    await dsl.goto("https://example.com/login")
    await dsl.fill(SemanticAction.LOGIN, "username", "alice")
    await dsl.click(SemanticAction.SUBMIT, "login-form")
"""

from __future__ import annotations

from src.backend.core.dsl_browser.dsl import (  # noqa: F401 — re-export
    BrowserConfig,
    BrowserDSL,
    PlaywrightPageProtocol,
    SelectorStrategy,
    SemanticAction,
    StepResult,
)

__all__ = (
    "BrowserConfig",
    "BrowserDSL",
    "PlaywrightPageProtocol",
    "SelectorStrategy",
    "SemanticAction",
    "StepResult",
)
