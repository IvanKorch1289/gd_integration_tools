"""RPA service settings (S164 W4).

Centralizes RPA-related configuration:
- PlaywrightBrowserPool size + browser-launch retry settings

Pattern: ``MailSettings`` / ``WSSettings`` — BaseSettingsWithLoader +
yaml_group + env_prefix.

Cycle 172 (ADR-0370, решение D3): desktop-*, browser-viewport-*, ocr-*
поля удалены — они не читались в рантайме, а ``extra="forbid"`` делал
их источником риска падения старта (унаследованный ``RPA_*`` env).
Параметры desktop-RPA pool'а задаются ctor-аргументами
``DesktopRPASessionPool``; флаг OCR живёт в
``feature_flags.rpa_ocr_enabled``.

DSL override (per-route): ``route.toml::[transport] pool_size``,
``message_timeout_s``, etc. — реализуется через ``DslService.get_route_overrides``
(S163 W15) и применяется per-action (W25) или per-connection (W33).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("RPASettings", "rpa_settings")


class RPASettings(BaseSettingsWithLoader):
    """Стандартные настройки RPA-сервисов.

    Используются в:
        * ``entrypoints/websocket/ws_handler.py`` (PlaywrightBrowserPool)
        * ``services/rpa/browser_pool.py`` (pool size / headless / retry)

    Per-route override через ``route.toml::[transport]`` (S163 W17).
    """

    yaml_group: ClassVar[str] = "rpa"
    model_config = SettingsConfigDict(env_prefix="RPA_", extra="forbid")

    # ── PlaywrightBrowserPool (anti-detection browser automation) ───
    #
    # Cycle 172 (ADR-0370, решение D3): desktop_* / browser_viewport_* /
    # ocr_* / desktop_cb_* / desktop_retry_* удалены — ни одно из этих
    # полей не читалось в рантайме (``grep`` по ``src/`` — 0 чтений),
    # а ``extra="forbid"`` превращал их в риск падения старта при
    # унаследованных ``RPA_*`` env-переменных. Параметры pool'а
    # desktop-RPA живут в самом ``DesktopRPASessionPool`` (ctor-аргументы).

    browser_pool_size: int = Field(
        default=2,
        ge=1,
        description="Количество предсозданных Playwright contexts в pool.",
    )
    browser_headless: bool = Field(
        default=True,
        description="Run browser in headless mode (False для локальной отладки).",
    )
    browser_launch_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description=(
            "2026-10-15: число ПОВТОРОВ (не попыток) browser launch при "
            "transient-crash (OOM killer, нехватка shm, segfault). "
            "0 = fail-fast (1 попытка); 2 (default) = 3 попытки. "
            "Реализация — core.resilience.retry.retry_async (tenacity, R-V15-8); "
            "при исчерпании частично созданные ресурсы освобождаются (R-V15-11)."
        ),
    )
    browser_launch_retry_base_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description=(
            "2026-10-15: базовая задержка exponential backoff для "
            "browser launch retry. 0.5s → 0.5s, 1.0s, 2.0s… "
            "Применяется только при browser_launch_max_retries > 0."
        ),
    )

    # ── Resilience defaults (apply unless overridden per-route) ────
    #
    # Cycle 172 (ADR-0370): desktop_cb_* / desktop_retry_max_attempts
    # удалены — не читались (0 чтений в ``src/``); пороги CB/retry
    # задаются на уровне самого ``DesktopRPASessionPool``/``RPACallPolicy``.


# Singleton per pattern (ws_settings, cache_settings, etc.).
# Lazy via __getattr__ in core.config.services to avoid module-load side effects.
rpa_settings = RPASettings()
