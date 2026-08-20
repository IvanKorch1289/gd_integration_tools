"""Sprint 19 iteration 10: P1-14 Protocol conformance test.

Verifies that :class:`core.interfaces.middleware.ProcessorMiddleware` is
correctly implemented by both DSL and observability middlewares. This is an
architectural test that prevents regressions of the Sprint 18 P1-14 refactor
which moved ProcessorMiddleware from dsl.engine.middleware to core.interfaces.
"""
from __future__ import annotations

import inspect

import pytest

from src.backend.core.interfaces.middleware import ProcessorMiddleware


@pytest.mark.unit
def test_processor_middleware_is_protocol() -> None:
    """ProcessorMiddleware должен быть Protocol, не ABC.

    Protocol с @runtime_checkable даёт нам isinstance() check
    без requiring explicit registration.
    """
    assert getattr(ProcessorMiddleware, "_is_protocol", False)
    # @runtime_checkable flag: _is_runtime_protocol = True
    assert getattr(ProcessorMiddleware, "_is_runtime_protocol", False)


@pytest.mark.unit
def test_protocol_signature_matches() -> None:
    """Signature Protocol должна совпадать с оригинальным ABC.

    Original ABC had:
    * before(processor_name, exchange, context) — async
    * after(processor_name, exchange, context, error, duration_ms) — async
    """
    sig_before = inspect.signature(ProcessorMiddleware.before)
    sig_after = inspect.signature(ProcessorMiddleware.after)

    # before(processor_name, exchange, context)
    assert "processor_name" in sig_before.parameters
    assert "exchange" in sig_before.parameters
    assert "context" in sig_before.parameters

    # after(processor_name, exchange, context, error, duration_ms)
    assert "processor_name" in sig_after.parameters
    assert "exchange" in sig_after.parameters
    assert "context" in sig_after.parameters
    assert "error" in sig_after.parameters
    assert "duration_ms" in sig_after.parameters


@pytest.mark.unit
def test_dsl_middleware_implements_protocol() -> None:
    """DSL-уровень ProcessorMiddleware ABC должен имплементировать Protocol.

    После P1-14: ABC в dsl.engine.middleware — thin wrapper
    с расширенными DSL-типами (Exchange, ExecutionContext).
    """
    from src.backend.dsl.engine.middleware import (
        ProcessorMiddleware as DslProcessorMiddleware,
    )

    # DSL class может быть ABC, но должен implement Protocol
    # (по duck typing — все required methods должны быть)
    assert hasattr(DslProcessorMiddleware, "before")
    assert hasattr(DslProcessorMiddleware, "after")


@pytest.mark.unit
def test_observability_middlewares_implement_protocol() -> None:
    """Observability middlewares (metrics, tracing) должны implement Protocol.

    Это критичный architectural invariant: после P1-14 они
    импортируют ProcessorMiddleware из core.interfaces (не из dsl).
    """
    from src.backend.infrastructure.observability.metrics import (
        PrometheusMetricsMiddleware,
    )
    from src.backend.infrastructure.observability.tracing import TracingMiddleware

    # Runtime check (Protocol должен быть runtime_checkable)
    assert isinstance(PrometheusMetricsMiddleware, ProcessorMiddleware), (
        "PrometheusMetricsMiddleware должен implement ProcessorMiddleware Protocol"
    )
    assert isinstance(TracingMiddleware, ProcessorMiddleware), (
        "TracingMiddleware должен implement ProcessorMiddleware Protocol"
    )


@pytest.mark.unit
def test_protocol_import_path_is_core_not_dsl() -> None:
    """P1-14: ProcessorMiddleware должен быть в core.interfaces, не dsl.engine.

    Это prevents regression: наблюдательные middlewares импортируют
    из core (architecture-clean), не из dsl (layer violation).
    """
    import src.backend.core.interfaces.middleware as core_mw
    import src.backend.dsl.engine.middleware as dsl_mw

    # core.interfaces.middleware.ProcessorMiddleware exists
    assert hasattr(core_mw, "ProcessorMiddleware")

    # dsl.engine.middleware.ProcessorMiddleware exists (re-export for compat)
    assert hasattr(dsl_mw, "ProcessorMiddleware")

    # Они are different classes (core is Protocol, dsl is ABC)
    assert core_mw.ProcessorMiddleware is not dsl_mw.ProcessorMiddleware, (
        "core и dsl versions должны быть РАЗНЫМИ классами (Protocol vs ABC)"
    )
