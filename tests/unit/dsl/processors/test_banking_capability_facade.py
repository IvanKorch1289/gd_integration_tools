"""Tests для banking capability facade migration (S190)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.security.capabilities import CapabilityDeniedError
from src.backend.dsl.engine.processors.ai_banking._base import _BankingAIProcessor

if TYPE_CHECKING:  # Cycle-19 (D-AUDIT-1909): unused but referenced for type stub.
    from typing import Any

    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


class _TestProcessor(_BankingAIProcessor):
    """Concrete subclass для тестирования base methods."""

    capability: str = "ai.banking.test"

    # Cycle 134: stub for abstract process() from BaseProcessor.
    # Tests don't exercise process() — only the helper methods.
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        pass  # pragma: no cover


class TestCheckCapabilityViaFacade:
    """Тесты _check_capability_via_facade helper."""

    @pytest.mark.asyncio
    async def test_successful_check_returns_true(self) -> None:
        """Successful capability check returns True."""
        processor = _TestProcessor()
        exchange = MagicMock()

        with patch(
            "src.backend.services.capabilities.facade.get_capability_facade",
        ) as mock_get:
            mock_facade = MagicMock()
            mock_facade.check_or_raise.return_value = True
            mock_get.return_value = mock_facade

            result = await processor._check_capability_via_facade(exchange)

        assert result is True
        exchange.fail.assert_not_called()

    @pytest.mark.asyncio
    async def test_capability_denied_returns_false(self) -> None:
        """CapabilityDeniedError → exchange.fail + return False."""
        processor = _TestProcessor()
        exchange = MagicMock()

        with patch(
            "src.backend.services.capabilities.facade.get_capability_facade",
        ) as mock_get:
            mock_facade = MagicMock()
            mock_facade.check_or_raise.side_effect = (
                CapabilityDeniedError(
                    plugin="test",
                    capability="ai.banking.test",
                    requested_scope=None,
                    declared_scope=None,
                )
            )
            mock_get.return_value = mock_facade

            result = await processor._check_capability_via_facade(exchange)

        assert result is False
        exchange.fail.assert_called_once()
        assert "capability_denied" in exchange.fail.call_args[0][0]

    @pytest.mark.asyncio
    async def test_other_exception_returns_false(self) -> None:
        """Other exceptions → exchange.fail с capability_check_error + False."""
        processor = _TestProcessor()
        exchange = MagicMock()

        with patch(
            "src.backend.services.capabilities.facade.get_capability_facade",
        ) as mock_get:
            mock_facade = MagicMock()
            mock_facade.check_or_raise.side_effect = RuntimeError("boom")
            mock_get.return_value = mock_facade

            result = await processor._check_capability_via_facade(exchange)

        assert result is False
        exchange.fail.assert_called_once()
        assert "capability_check_error" in exchange.fail.call_args[0][0]

    @pytest.mark.asyncio
    async def test_plugin_attribution(self) -> None:
        """Plugin name включает имя класса processor'а."""
        processor = _TestProcessor()
        exchange = MagicMock()

        with patch(
            "src.backend.services.capabilities.facade.get_capability_facade",
        ) as mock_get:
            mock_facade = MagicMock()
            mock_facade.check_or_raise.return_value = True
            mock_get.return_value = mock_facade

            await processor._check_capability_via_facade(exchange)

        # Verify plugin attribution includes class name
        call_kwargs = mock_facade.check_or_raise.call_args
        # Cycle 134: production hardcodes full module path
        # "dsl.engine.processors.ai_banking.{class_name}" (S190 refactor
        # moved base.py there from ai_banking/ subpackage). Test updated.
        assert "dsl.engine.processors.ai_banking._TestProcessor" in call_kwargs.kwargs["plugin"]
        assert call_kwargs.kwargs["capability"] == "ai.banking.test"


class TestIdentityMigration:
    """Тесты миграции identity.py (двух процессоров)."""

    @pytest.mark.asyncio
    async def test_identity_check_capability_uses_facade(self) -> None:
        """KycAmlVerifyProcessor._check_capability использует facade."""
        from src.backend.dsl.engine.processors.ai_banking.identity import (
            KycAmlVerifyProcessor,
        )

        processor = KycAmlVerifyProcessor(
            jurisdiction="RU",
        )
        exchange = MagicMock()

        with patch(
            "src.backend.services.capabilities.facade.get_capability_facade",
        ) as mock_get:
            mock_facade = MagicMock()
            mock_facade.check_or_raise.return_value = True
            mock_get.return_value = mock_facade

            await processor._check_capability(exchange, MagicMock())

        mock_facade.check_or_raise.assert_called_once()
        call_kwargs = mock_facade.check_or_raise.call_args
        assert call_kwargs.kwargs["capability"] == "ai.banking.kyc_aml"
