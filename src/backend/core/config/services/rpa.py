"""RPA service settings (S164 W4).

Centralizes RPA-related configuration:
- Desktop RPA session pool (timeout, TTL, max sessions)
- PlaywrightBrowserPool size + per-action settings
- OCR backend settings (placeholder for future expansion)

Pattern: ``MailSettings`` / ``WSSettings`` — BaseSettingsWithLoader +
yaml_group + env_prefix.

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
        * ``services/rpa/desktop_session_pool.py`` (DesktopRPASessionPool)
        * ``services/rpa/desktop_rpa_client.py`` (DesktopRpaClient)
        * ``services/rpa/ocr_processor.py`` (feature-flag fallback)

    Per-route override через ``route.toml::[transport]`` (S163 W17).
    """

    yaml_group: ClassVar[str] = "rpa"
    model_config = SettingsConfigDict(env_prefix="RPA_", extra="forbid")

    # ── Desktop RPA session pool (windows-worker sidecar) ──────────

    desktop_base_url: str | None = Field(
        default=None,
        description="URL windows-worker sidecar (``http://windows-worker:9001``).",
    )
    desktop_api_key: str | None = Field(
        default=None,
        description="API-key для аутентификации sidecar'а (X-API-Key header).",
    )
    desktop_timeout: float = Field(
        default=30.0,
        gt=0,
        description="Connect+read timeout для DesktopRPA HTTP-запросов (seconds).",
    )
    desktop_ttl_seconds: float = Field(
        default=1800.0,
        gt=0,
        description="Idle TTL для DesktopRPA session до закрытия (default 30min).",
    )
    desktop_max_sessions: int = Field(
        default=16,
        gt=0,
        description="Upper limit для DesktopRPA session pool (per app_name).",
    )

    # ── PlaywrightBrowserPool (anti-detection browser automation) ───

    browser_pool_size: int = Field(
        default=2,
        ge=1,
        description="Количество предсозданных Playwright contexts в pool.",
    )
    browser_kind: str = Field(
        default="chromium",
        description="Browser engine: ``chromium`` / ``firefox`` / ``webkit``.",
    )
    browser_headless: bool = Field(
        default=True,
        description="Run browser in headless mode (False для локальной отладки).",
    )
    browser_viewport_width: int = Field(
        default=1280, gt=0, description="Browser viewport width (pixels)."
    )
    browser_viewport_height: int = Field(
        default=720, gt=0, description="Browser viewport height (pixels)."
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

    # ── OCR backend (feature-flag gated) ─────────────────────────────

    ocr_enabled: bool = Field(default=False)
    ocr_default_lang: str = Field(
        default="eng+rus",
        description="Default Tesseract language code (``eng``, ``rus``, ``eng+rus``).",
    )

    # ── Resilience defaults (apply unless overridden per-route) ────

    desktop_cb_failure_threshold: int = Field(
        default=5, gt=0, description="CB failure threshold для DesktopRpaClient/Pool."
    )
    desktop_cb_recovery_seconds: float = Field(
        default=30.0, gt=0, description="CB recovery timeout (seconds)."
    )
    desktop_retry_max_attempts: int = Field(
        default=3, gt=0, description="Max retry attempts для DesktopRpaClient.execute."
    )


# Singleton per pattern (ws_settings, cache_settings, etc.).
# Lazy via __getattr__ in core.config.services to avoid module-load side effects.
rpa_settings = RPASettings()
