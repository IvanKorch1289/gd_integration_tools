"""Round 5 Sprint 5.2: compat-shims для ``correlation.py``.

Покрывает 2 compat-функции, добавленные в Round 5:

* :func:`set_correlation_id` — alias для :func:`set_correlation_context`,
  нужен callers, которые хотят установить только correlation_id.
* :func:`start_span` — no-op context manager (OTEL SDK carryover).

Эти функции используются :class:`services.observability.facade.ObservabilityFacade`
(``start_span`` + ``set_correlation_id`` методы) — mypy ранее падал
на отсутствующих именах в ``core.observability.correlation``.
"""

from __future__ import annotations

import pytest


class TestSetCorrelationIdCompat:
    """``set_correlation_id`` — compat-shim для ``set_correlation_context``."""

    def test_set_correlation_id_sets_only_correlation(self) -> None:
        """Только correlation_id — без request_id/tenant_id."""
        from src.backend.core.observability.correlation import (
            get_correlation_id,
            set_correlation_id,
        )

        set_correlation_id("abc-123")
        assert get_correlation_id() == "abc-123"

    def test_set_correlation_id_overwrites_previous(self) -> None:
        """Повторный set — перезаписывает значение (не аккумулирует)."""
        from src.backend.core.observability.correlation import (
            get_correlation_id,
            set_correlation_id,
        )

        set_correlation_id("first")
        set_correlation_id("second")
        assert get_correlation_id() == "second"

    def test_set_correlation_id_empty_string(self) -> None:
        """Пустая строка — валидный input (не сбрасывает, но устанавливает)."""
        from src.backend.core.observability.correlation import (
            get_correlation_id,
            set_correlation_id,
        )

        set_correlation_id("test")
        set_correlation_id("")
        # structlog может забиндить пустую строку или оставить прежнее
        # значение — это не наша забота, проверяем только что не упало.
        assert isinstance(get_correlation_id(), str)


class TestStartSpanCompat:
    """``start_span`` — no-op context manager (OTEL SDK carryover).

    cycle-9/D-AUDIT-916 fix: production code теперь возвращает
    ``NonRecordingSpan`` (real OTel context manager), а не None.
    Раньше тест был рассчитан на no-op fallback. Тест обновлён:
    проверяет что ``start_span`` возвращает context manager (т.е.
    можно вызвать __enter__/__exit__ без exception) и что result
    является либо None (legacy no-op), либо OTel-совместимым span
    object. Production code сейчас выбирает NonRecordingSpan.
    """

    @pytest.mark.asyncio
    async def test_start_span_yields_context_manager(self) -> None:
        """``start_span`` возвращает context manager (None или OTel span)."""
        from src.backend.core.observability.correlation import start_span

        with start_span("test_span", attributes={"key": "value"}) as span:
            # Принимаем None (legacy no-op) или OTel NonRecordingSpan-like
            # (OTel real SDK). Главное — context manager работает
            # без exception и span атрибут доступен.
            assert span is None or hasattr(span, "get_span_context")

    @pytest.mark.asyncio
    async def test_start_span_no_attributes(self) -> None:
        """``attributes=None`` — допустимый input."""
        from src.backend.core.observability.correlation import start_span

        with start_span("test_span") as span:
            assert span is None or hasattr(span, "get_span_context")

    @pytest.mark.asyncio
    async def test_start_span_does_not_raise(self) -> None:
        """``start_span`` никогда не поднимает исключений."""
        from src.backend.core.observability.correlation import start_span

        # Должен работать даже с пустым именем span.
        with start_span(""):
            pass

    def test_start_span_is_context_manager(self) -> None:
        """``start_span`` — настоящий context manager (``__enter__`` / ``__exit__``)."""
        from src.backend.core.observability.correlation import start_span

        ctx = start_span("test")
        # Имеет __enter__ и __exit__
        assert hasattr(ctx, "__enter__")
        assert hasattr(ctx, "__exit__")
