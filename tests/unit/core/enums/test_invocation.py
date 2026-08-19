"""Tests for core/enums/invocation.py (cycle 238 — coverage push).

Per CYCLE-220 analysis, coverage target 77% → 80% (analyst #12).
\`core/enums/invocation.py\` (26 LOC, 688 bytes) — small public
StrEnum (InvokeMode, BrokerKind) без тестов.
"""

from __future__ import annotations


def test_invoke_mode_has_two_values() -> None:
    """InvokeMode: direct, event."""
    from src.backend.core.enums.invocation import InvokeMode
    assert len(InvokeMode) == 2


def test_invoke_mode_values() -> None:
    """\`direct='direct', event='event'\` — StrEnum."""
    from src.backend.core.enums.invocation import InvokeMode
    assert InvokeMode.direct.value == "direct"
    assert InvokeMode.event.value == "event"


def test_broker_kind_has_three_values() -> None:
    """BrokerKind: redis, rabbit, kafka."""
    from src.backend.core.enums.invocation import BrokerKind
    assert len(BrokerKind) == 3


def test_broker_kind_values() -> None:
    """\`redis='redis', rabbit='rabbit', kafka='kafka'\`."""
    from src.backend.core.enums.invocation import BrokerKind
    assert BrokerKind.redis.value == "redis"
    assert BrokerKind.rabbit.value == "rabbit"
    assert BrokerKind.kafka.value == "kafka"


def test_invocation_module_dunder_all() -> None:
    """\`__all__ = ('BrokerKind', 'InvokeMode')\`."""
    import src.backend.core.enums.invocation as mod
    assert mod.__all__ == ("BrokerKind", "InvokeMode")


def test_invoke_mode_string_comparison() -> None:
    """StrEnum: \`str(InvokeMode.direct) == 'direct'\`."""
    from src.backend.core.enums.invocation import InvokeMode
    assert str(InvokeMode.direct) == "direct"
    assert str(InvokeMode.event) == "event"
