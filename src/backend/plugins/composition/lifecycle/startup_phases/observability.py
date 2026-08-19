"""Sprint 15 P1-12: observability startup phases.

Phases:
- :func:`phase_otel_traces` — OTel TracerProvider baseline (OTEL_ENABLED env)
- :func:`phase_otel_metrics` — OTel MeterProvider (OTLP_METRICS_ENABLED env)
- :func:`phase_config_validator` — cross-settings ConfigValidator (Sprint 16 B-2)
- :func:`phase_sentry_init` — Sentry error tracking init (graceful)
- :func:`phase_logsink_router` — LogSink router (Wave 2.5)
- :func:`phase_audit_hmac_verify` — periodic Audit HMAC-chain verify (B-series FIX-H5)
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_logger = get_logger("application.startup.observability")


async def phase_otel_traces(app: FastAPI) -> None:  # noqa: ARG001
    """OTel TracerProvider baseline (OTEL_ENABLED env)."""
    if os.environ.get("OTEL_ENABLED", "false").lower() != "true":
        return
    try:
        from src.backend.infrastructure.observability.otel import configure_otel

        configure_otel(
            service_name=os.environ.get("OTEL_SERVICE_NAME", "gd_integration"),
            exporter=os.environ.get("OTEL_EXPORTER", "console"),
            endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
            environment=os.environ.get("APP_ENVIRONMENT", "development"),
        )
    except Exception as otel_exc:
        _logger.warning(
            "OTel baseline configure skipped: %s "
            "(приложение продолжит без базового TracerProvider)",
            otel_exc,
        )


async def phase_otel_metrics(app: FastAPI) -> None:  # noqa: ARG001
    """OTel MeterProvider (OTLP_METRICS_ENABLED env)."""
    if os.environ.get("OTLP_METRICS_ENABLED", "false").lower() != "true":
        return
    try:
        from src.backend.infrastructure.observability.otel import setup_otel_metrics

        setup_otel_metrics(
            service_name=os.environ.get("OTEL_SERVICE_NAME", "gd_integration"),
            exporter=os.environ.get("OTEL_METRICS_EXPORTER", "console"),
            endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
            environment=os.environ.get("APP_ENVIRONMENT", "development"),
        )
    except Exception as metrics_exc:
        _logger.warning(
            "OTel metrics setup skipped: %s "
            "(приложение продолжит без OTLP metrics-канала)",
            metrics_exc,
        )


async def phase_config_validator(app: FastAPI) -> None:  # noqa: ARG001
    """Cross-settings ConfigValidator (Sprint 16 Wave 3, CP-24, B-2, B-9).

    Hard errors (ProductionConfigError) propagate; other exceptions log+continue.
    """
    try:
        from src.backend.core.config.settings import settings as _cv_settings
        from src.backend.core.config.validator import (
            ConfigSeverity,
            ProductionConfigError,
            validate_startup_config,
        )
        from src.backend.core.config.waf import waf_settings as _cv_waf_settings

        _cv_violations = validate_startup_config(_cv_settings, _cv_waf_settings)
        for _cv_v in _cv_violations:
            _payload = (
                "[%s] %s field=%s recommendation=%s context=%s",
                _cv_v.code,
                _cv_v.message,
                _cv_v.field,
                _cv_v.recommendation,
                _cv_v.context,
            )
            if _cv_v.severity == ConfigSeverity.CRITICAL:
                _logger.critical(*_payload)
            elif _cv_v.severity == ConfigSeverity.WARNING:
                _logger.warning(*_payload)
            else:
                _logger.info(*_payload)
    except ProductionConfigError as cfg_exc:
        _logger.critical("Конфигурация production не прошла валидацию: %s", cfg_exc)
        raise
    except Exception as cfg_exc:
        _logger.warning(
            "ConfigValidator skipped: %s "
            "(приложение продолжит без cross-settings проверки)",
            cfg_exc,
        )


async def phase_sentry_init(app: FastAPI) -> None:  # noqa: ARG001
    """Sentry error tracking init (graceful, never blocks)."""
    if os.environ.get("SENTRY_ENABLED", "false").lower() != "true":
        return
    try:
        from src.backend.infrastructure.observability.sentry import init_sentry

        init_sentry(
            dsn=os.environ.get("SENTRY_DSN", ""),
            environment=os.environ.get("APP_ENVIRONMENT", "development"),
        )
    except Exception as sentry_exc:
        _logger.warning(
            "Sentry init skipped: %s (приложение продолжит без error-tracking)",
            sentry_exc,
        )


async def phase_logsink_router(app: FastAPI) -> None:  # noqa: ARG001
    """LogSink router (Wave 2.5) — multi-sink log routing."""
    try:
        from src.backend.infrastructure.observability.logsink import init_logsink_router

        init_logsink_router()
    except Exception as ls_exc:
        _logger.warning(
            "LogSink router init skipped: %s "
            "(приложение продолжит со single-sink logging)",
            ls_exc,
        )


async def phase_audit_hmac_verify(app: FastAPI) -> None:  # noqa: ARG001
    """Periodic :meth:`ImmutableAuditStore.verify` через TaskRegistry (FIX-H5).

    Opt-in via feature flag; periodic check не блокирует startup.
    """
    try:
        from src.backend.core.config.features import feature_flags
        from src.backend.services.audit.chain_verifier import (
            schedule_periodic_chain_verify,
        )

        if getattr(feature_flags, "audit_hmac_periodic_verify", False):
            await schedule_periodic_chain_verify()
            _logger.info("AuditChainVerifier scheduled (periodic HMAC verify)")
    except Exception as audit_exc:
        _logger.warning(
            "AuditChainVerifier bootstrap skipped: %s "
            "(приложение продолжит без periodic HMAC verify)",
            audit_exc,
        )


__all__ = (
    "phase_otel_traces",
    "phase_otel_metrics",
    "phase_config_validator",
    "phase_sentry_init",
    "phase_logsink_router",
    "phase_audit_hmac_verify",
)
