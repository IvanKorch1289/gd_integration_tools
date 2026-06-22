"""Sentry initialization — structured error tracking.

Опциональная интеграция: если SENTRY_DSN не задан, skip.
PII scrubbing через Presidio перед отправкой в Sentry.

Usage в main.py::

    from src.backend.infrastructure.observability.sentry_init import init_sentry
    init_sentry()
"""

from __future__ import annotations

import os
from typing import Any

from src.backend.core.logging import get_logger
__all__ = ("init_sentry",)

logger = get_logger("infra.sentry")


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
    """Sentry ``before_send`` хук: маскирует PII перед отправкой (V15 S1).

    Покрывает:

    * ``event['message']`` — основное сообщение;
    * ``event['exception']['values'][i]['value']`` — текст исключения;
    * ``event['request']['data']`` — POST/PATCH тело;
    * ``event['breadcrumbs']['values'][i]['message']`` — log entries;
    * ``event['extra']`` / ``event['contexts']`` — пользовательские поля.

    Все 5 типов PII из S1 DoD (email/phone/passport/snils/inn) +
    credit card покрываются :func:`redact_for_observability`.
    Опциональный fallback на Presidio активируется через env
    ``PII_PRESIDIO_ENABLED=true`` (для углублённой детекции в проде).
    """
    from src.backend.infrastructure.observability.pii_filter import (
        redact_for_observability,
    )

    try:
        if "message" in event:
            event["message"] = redact_for_observability(event["message"])

        request = event.get("request")
        if isinstance(request, dict):
            for key in ("data", "query_string", "cookies", "headers"):
                if key in request:
                    request[key] = redact_for_observability(request[key])

        exception = event.get("exception")
        if isinstance(exception, dict):
            for val in exception.get("values", []):
                if isinstance(val, dict) and "value" in val:
                    val["value"] = redact_for_observability(val["value"])

        breadcrumbs = event.get("breadcrumbs")
        if isinstance(breadcrumbs, dict):
            for crumb in breadcrumbs.get("values", []):
                if isinstance(crumb, dict):
                    if "message" in crumb:
                        crumb["message"] = redact_for_observability(crumb["message"])
                    if "data" in crumb:
                        crumb["data"] = redact_for_observability(crumb["data"])

        for key in ("extra", "contexts", "tags"):
            if key in event:
                event[key] = redact_for_observability(event[key])

        if os.environ.get("PII_PRESIDIO_ENABLED", "").lower() == "true":
            _scrub_with_presidio(event)

    except Exception as exc:
        logger.debug("Sentry PII scrub failed: %s", exc)

    return event


def _scrub_with_presidio(event: dict[str, Any]) -> None:
    """Опц. углублённая PII-детекция через Presidio (feature-flag).

    Активируется ``PII_PRESIDIO_ENABLED=true``. При отсутствии Presidio в
    окружении функция тихо ничего не делает.
    """
    try:
        from src.backend.infrastructure.security.presidio_sanitizer import (
            get_presidio_sanitizer,
        )

        sanitizer = get_presidio_sanitizer()
        message = event.get("message")
        if isinstance(message, str) and len(message) >= 3:
            try:
                event["message"] = sanitizer.sanitize(message)
            except Exception:
                pass
    except ImportError:
        return
