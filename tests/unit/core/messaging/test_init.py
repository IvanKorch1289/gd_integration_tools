"""Unit-тесты ``core.messaging`` — coverage ratchet (S49 W5).

core/messaging/__init__.py — messaging contracts facade: re-exports
Protocol + Pydantic models + Fake implementations for unit tests
(OutboxBackend, OutboxEvent, OutboxEventStatus, FakeOutbox).
~12 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/Protocol identity.
"""

from __future__ import annotations

import pytest

from src.backend.core import messaging
from src.backend.core.messaging import (
    FakeOutbox,
    OutboxBackend,
    OutboxEvent,
    OutboxEventStatus,
)


@pytest.mark.unit
class TestMessagingFacadeAllExports:
    """``__all__`` audit + class/Protocol identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "FakeOutbox",
            "OutboxBackend",
            "OutboxEvent",
            "OutboxEventStatus",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(messaging, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in messaging.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(messaging.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает messaging contracts (Outbox/Inbox/DLQ)."""
        assert messaging.__doc__ is not None
        assert "Outbox" in messaging.__doc__ or "messaging" in messaging.__doc__.lower()


@pytest.mark.unit
class TestMessagingFacadeIdentity:
    """Identity checks для re-exports."""

    def test_fake_outbox_is_class(self) -> None:
        """``FakeOutbox`` — class (in-memory outbox stub)."""
        assert isinstance(FakeOutbox, type)

    def test_outbox_backend_is_protocol_or_class(self) -> None:
        """``OutboxBackend`` — Protocol class (duck-typed contract)."""
        # Protocol classes pass isinstance check.
        assert isinstance(OutboxBackend, type)

    def test_outbox_event_is_class(self) -> None:
        """``OutboxEvent`` — class (Pydantic / dataclass)."""
        assert isinstance(OutboxEvent, type)

    def test_outbox_event_status_is_class(self) -> None:
        """``OutboxEventStatus`` — class (enum / dataclass)."""
        assert isinstance(OutboxEventStatus, type)

    def test_fake_outbox_instantiation(self) -> None:
        """``FakeOutbox()`` — instantiable stub."""
        fake = FakeOutbox()
        assert fake is not None
