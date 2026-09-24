"""Temporal interceptors factory (v6 W2).

Per v6 W2 spec: «Создать единственную фабрику build_temporal_interceptors().
Использовать её во всех Temporal client constructors».

Replaces inconsistent per-callsite OTEL interceptor instantiation:
    - ``temporal_client.py`` использовал ``temporalio.opentelemetry
      OpenTelemetryTracingInterceptor`` (НЕ существует в Temporal SDK 1.33).
    - ``temporal_backend.py`` использовал ``temporalio.contrib.opentelemetry
      TracingInterceptor`` (КОРРЕКТНЫЙ путь для SDK 1.33).

После этого модуля: все Temporal client constructors импортируют
``build_temporal_interceptors()`` → единая фабрика, единый API path,
graceful fallback на логирование если OTEL SDK не установлен.

Per v6 W2 «Один поддерживаемый Temporal SDK API»:
    canonical path = ``temporalio.contrib.opentelemetry.TracingInterceptor``
    (SDK 1.33+, требует ``pip install 'temporalio[opentelemetry]'``).
"""

from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger("infra.workflow.temporal_interceptors")

# Canonical SDK 1.33+ OTEL TracingInterceptor module path.
# Per v6 W2: «Один поддерживаемый Temporal SDK API».
CANONICAL_OTEL_MODULE = "temporalio.contrib.opentelemetry"
CANONICAL_OTEL_CLASS = "TracingInterceptor"


def build_temporal_interceptors() -> list[Any]:
    """Единственная фабрика Temporal interceptors (v6 W2).

    Returns:
        list of interceptor instances для ``Client.connect(interceptors=...)``.

    Per v6 W2:
        - Один поддерживаемый Temporal SDK API (temporalio.contrib.opentelemetry).
        - Graceful fallback: если OTEL SDK не установлен → [] + WARNING log
          (operators MUST знать что OTel spans не эмитятся, иначе
          observability gap невидим).
        - Реальный import (НЕ mock): если module not found → bare ``except``
          без подмены.
    """
    interceptors: list[Any] = []
    try:
        # SDK 1.33+ canonical path: ``temporalio.contrib.opentelemetry``.
        # Legacy path (``temporalio.opentelemetry.OpenTelemetryTracingInterceptor``)
        # НЕ существует в SDK 1.33 — убран per v6 audit.
        import importlib

        otel_module = importlib.import_module(CANONICAL_OTEL_MODULE)
        interceptor_cls = getattr(otel_module, CANONICAL_OTEL_CLASS)
        interceptors.append(interceptor_cls())
        _logger.debug(
            "temporal.otel.interceptor.enabled module=%s", CANONICAL_OTEL_MODULE
        )
    except ImportError as exc:
        # Graceful fallback per v6 W2: «Graceful fallback тестируется отдельно
        # и не считается propagation PASS».
        _logger.warning(
            "temporal.otel.interceptor.unavailable",
            extra={
                "hint": (
                    "pip install 'temporalio[opentelemetry]' для OTel-трейсов Temporal. "
                    f"canonical path={CANONICAL_OTEL_MODULE}.{CANONICAL_OTEL_CLASS}"
                ),
                "import_error": str(exc),
            },
        )
    return interceptors


__all__ = ("build_temporal_interceptors",)
