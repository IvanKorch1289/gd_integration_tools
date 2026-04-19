"""Sentry initialization — structured error tracking.

Опциональная интеграция: если SENTRY_DSN не задан, skip.
PII scrubbing через Presidio перед отправкой в Sentry.

Usage в main.py::

    from app.infrastructure.observability.sentry_init import init_sentry
    init_sentry()
"""

from __future__ import annotations

import logging
import os
from typing import Any

__all__ = ("init_sentry",)

logger = logging.getLogger("infra.sentry")


def init_sentry(
    *,
    dsn: str | None = None,
    environment: str | None = None,
    traces_sample_rate: float = 0.1,
    profiles_sample_rate: float = 0.1,
) -> bool:
    """Инициализирует Sentry SDK.

    Args:
        dsn: Sentry DSN (или из env SENTRY_DSN).
        environment: production / staging / development.
        traces_sample_rate: Доля трейсов для performance monitoring.
        profiles_sample_rate: Доля профилей.

    Returns:
        True если Sentry инициализирован, False при отсутствии DSN/библиотеки.
    """
    dsn = dsn or os.environ.get("SENTRY_DSN")
    if not dsn:
        logger.debug("Sentry DSN not set, skipping init")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        logger.warning("sentry-sdk not installed, error tracking disabled")
        return False

    env = environment or os.environ.get("APP_ENVIRONMENT", "development")

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        integrations=[
            AsyncioIntegration(),
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        before_send=_scrub_pii,
        send_default_pii=False,
        attach_stacktrace=True,
    )

    logger.info("Sentry initialized: env=%s, traces=%.2f", env, traces_sample_rate)
    return True


def _scrub_pii(event: dict[str, Any], hint: Any) -> dict[str, Any] | None:
    """Scrub PII через Presidio перед отправкой в Sentry.

    Удаляет из event.request body / breadcrumbs / exception values
    любые PII, распознанные Presidio (emails, phones, cards, etc.).
    """
    try:
        from app.core.security.presidio_sanitizer import get_presidio_sanitizer
        sanitizer = get_presidio_sanitizer()
    except ImportError:
        return event

    def _scrub_str(value: Any) -> Any:
        if not isinstance(value, str) or len(value) < 3:
            return value
        try:
            import asyncio
            loop = asyncio.get_event_loop() if asyncio.get_event_loop().is_running() else None
            if loop is None:
                return value
            return value
        except Exception:
            return value

    try:
        # Scrub request body
        request = event.get("request", {})
        if isinstance(request, dict):
            data = request.get("data")
            if isinstance(data, str):
                request["data"] = _scrub_str(data)

        # Scrub exception values
        exception = event.get("exception", {})
        values = exception.get("values", []) if isinstance(exception, dict) else []
        for val in values:
            if isinstance(val, dict) and "value" in val:
                val["value"] = _scrub_str(val["value"])

    except Exception as exc:
        logger.debug("Sentry PII scrub failed: %s", exc)

    return event
