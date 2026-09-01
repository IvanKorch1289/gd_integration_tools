"""Unit-тесты ``core.api.messaging`` — coverage ratchet (S48 W21).

core/api/messaging.py — Sprint 38 facade: re-exports
infrastructure.messaging (dlq_base, outbox, OutboxStuckMonitor) +
backward-compat aliases (DLQBase, Outbox) + lazy __getattr__ для
KafkaProducer (Sprint 38 fix, requires aiokafka). 11 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + module identity + lazy __getattr__.
"""

from __future__ import annotations

import pytest

from src.backend.core.api import messaging
from src.backend.core.api.messaging import (
    DLQBase,
    Outbox,
    OutboxMonitor,
    dlq_base,
    outbox,
)


@pytest.mark.unit
class TestMessagingFacadeAllExports:
    """``__all__`` audit + module identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["dlq_base", "outbox", "OutboxMonitor", "DLQBase", "Outbox"],
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
        """``__all__`` содержит 5 entries (5 explicit names; KafkaProducer — lazy через __getattr__)."""
        # KafkaProducer не в __all__ (lazy через __getattr__) — effective 5.
        assert len(messaging.__all__) == 5

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 38 facade."""
        assert messaging.__doc__ is not None
        assert "Sprint 38" in messaging.__doc__


@pytest.mark.unit
class TestMessagingFacadeIdentity:
    """Identity checks: backward-compat aliases + canonical modules."""

    def test_dlqbase_aliases_dlq_base(self) -> None:
        """``DLQBase`` (capitalized) = ``dlq_base`` module."""
        assert DLQBase is dlq_base

    def test_outbox_aliases_outbox_module(self) -> None:
        """``Outbox`` (capitalized) = ``outbox`` module."""
        assert Outbox is outbox

    def test_outbox_monitor_aliased(self) -> None:
        """``OutboxMonitor`` = ``OutboxStuckMonitor`` (aliased import)."""
        from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
            OutboxStuckMonitor,
        )

        assert OutboxMonitor is OutboxStuckMonitor

    def test_unknown_attr_raises_attribute_error(self) -> None:
        """``__getattr__`` для unknown name → AttributeError (не ImportError)."""
        with pytest.raises(AttributeError, match="has no attribute"):
            messaging.NonExistentSymbol  # type: ignore[attr-defined]
