"""Smoke-тесты для src/backend/core/observability/baggage.py.

Покрывает:
    - roundtrip set/get baggage;
    - восстановление предыдущего context в with_baggage;
    - ensure_required_baggage в strict=True (pass и raise);
    - ensure_required_baggage в strict=False (default-OFF).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.core.observability.baggage import (
    MissingBaggageError,
    ensure_required_baggage,
    get_baggage,
    with_baggage,
)


class TestSetGetBaggageRoundtrip:
    """Тест roundtrip: set_baggage → get_baggage возвращает те же значения."""

    def test_set_get_baggage_roundtrip(self) -> None:
        """Проверяет, что все 4 поля корректно записываются и читаются."""
        # Используем изолированный OTel context через with_baggage для чистоты
        import asyncio

        async def _run() -> None:
            async with with_baggage(
                route_name="credit_check_v2",
                tenant_id="bank_alpha",
                business_op="credit.score.calculate",
                correlation_id="req-abc123",
            ):
                bag = get_baggage()
                assert bag["route_name"] == "credit_check_v2"
                assert bag["tenant_id"] == "bank_alpha"
                assert bag["business_op"] == "credit.score.calculate"
                assert bag["correlation_id"] == "req-abc123"

        asyncio.run(_run())


class TestWithBaggageContextManagerRestoresPrevious:
    """Тест: with_baggage восстанавливает предыдущий context на выходе."""

    def test_baggage_context_manager_restores_previous(self) -> None:
        """Проверяет, что после выхода из with_baggage предыдущие значения восстановлены."""
        import asyncio

        async def _run() -> None:
            # Установить внешний baggage
            async with with_baggage(
                route_name="outer_route",
                tenant_id="tenant_outer",
                business_op="outer.op",
                correlation_id="outer-corr-id",
            ):
                # Убедиться, что внешний baggage установлен
                outer_bag = get_baggage()
                assert outer_bag["route_name"] == "outer_route"

                # Войти во вложенный context
                async with with_baggage(
                    route_name="inner_route",
                    tenant_id="tenant_inner",
                    business_op="inner.op",
                    correlation_id="inner-corr-id",
                ):
                    inner_bag = get_baggage()
                    assert inner_bag["route_name"] == "inner_route"
                    assert inner_bag["tenant_id"] == "tenant_inner"

                # После выхода из вложенного — должны видеть внешний context
                restored_bag = get_baggage()
                assert restored_bag["route_name"] == "outer_route"
                assert restored_bag["tenant_id"] == "tenant_outer"

        asyncio.run(_run())


class TestEnsureRequiredBaggagePasses:
    """Тест: ensure_required_baggage не raises при полном baggage в strict=True."""

    def test_ensure_required_baggage_passes_when_complete(self) -> None:
        """Проверяет, что ensure_required_baggage проходит при всех 4 полях."""
        import asyncio
        from unittest.mock import MagicMock

        async def _run() -> None:
            async with with_baggage(
                route_name="health_check",
                tenant_id="sys",
                business_op="health.ping",
                correlation_id="corr-001",
            ):
                # Патчим _get_feature_flags чтобы вернуть strict=True
                mock_flags = MagicMock()
                mock_flags.tracing_baggage_strict = True
                with patch(
                    "src.backend.core.observability.baggage._get_feature_flags",
                    return_value=mock_flags,
                ):
                    # Должно пройти без исключений
                    ensure_required_baggage()
                    assert mock_flags.tracing_baggage_strict is True

        asyncio.run(_run())


class TestEnsureRequiredBaggageRaisesWhenStrictAndMissing:
    """Тест: ensure_required_baggage raises MissingBaggageError при неполном baggage в strict=True."""

    def test_ensure_required_baggage_raises_when_strict_and_missing(self) -> None:
        """Проверяет, что MissingBaggageError возбуждается при отсутствующих полях."""
        import asyncio
        from unittest.mock import MagicMock

        async def _run() -> None:
            # Устанавливаем только часть полей (нет business_op и correlation_id)
            async with with_baggage(
                route_name="partial_route",
                tenant_id="bank_beta",
                # business_op и correlation_id намеренно пропущены
            ):
                mock_flags = MagicMock()
                mock_flags.tracing_baggage_strict = True
                with patch(
                    "src.backend.core.observability.baggage._get_feature_flags",
                    return_value=mock_flags,
                ):
                    with pytest.raises(MissingBaggageError) as exc_info:
                        ensure_required_baggage()

                    error = exc_info.value
                    assert "business_op" in error.missing
                    assert "correlation_id" in error.missing
                    # Установленные поля не должны быть в missing
                    assert "route_name" not in error.missing
                    assert "tenant_id" not in error.missing

        asyncio.run(_run())


class TestStrictModeDefaultOff:
    """Тест: ensure_required_baggage не raises при strict=False (default)."""

    def test_strict_mode_default_off(self) -> None:
        """Проверяет, что при strict=False ensure_required_baggage не raises даже при пустом baggage."""
        import asyncio
        from unittest.mock import MagicMock

        async def _run() -> None:
            # Вызываем без установки каких-либо полей baggage
            mock_flags = MagicMock()
            mock_flags.tracing_baggage_strict = False
            with patch(
                "src.backend.core.observability.baggage._get_feature_flags",
                return_value=mock_flags,
            ):
                # Должно пройти без исключений, несмотря на пустой baggage
                ensure_required_baggage()
                assert mock_flags.tracing_baggage_strict is False

        asyncio.run(_run())
