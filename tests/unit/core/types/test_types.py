"""Tests for core/types/ (S97 — coverage push).

Покрывает: data_kind.py, side_effect.py, watermark.py, invocation_command.py.
"""

from __future__ import annotations


def test_data_kind() -> None:
    """DataKind StrEnum: SINGLE='single', BATCH='batch', STREAM='stream'."""
    from src.backend.core.types.data_kind import DataKind

    assert DataKind.SINGLE.value == "single"
    assert DataKind.BATCH.value == "batch"
    assert DataKind.STREAM.value == "stream"
    assert len(DataKind) == 3
    # StrEnum mixin: == сравнение со строкой.
    assert DataKind.SINGLE == "single"


def test_data_kind_dunder_all() -> None:
    """__all__ = ('DataKind',)."""
    import src.backend.core.types.data_kind as mod

    assert mod.__all__ == ("DataKind",)


def test_side_effect_kind() -> None:
    """SideEffectKind StrEnum: PURE/STATEFUL/SIDE_EFFECTING."""
    from src.backend.core.types.side_effect import SideEffectKind

    assert SideEffectKind.PURE.value == "pure"
    assert SideEffectKind.STATEFUL.value == "stateful"
    assert SideEffectKind.SIDE_EFFECTING.value == "side_effecting"
    assert len(SideEffectKind) == 3
    assert SideEffectKind.PURE == "pure"


def test_side_effect_kind_dunder_all() -> None:
    """__all__ = ('SideEffectKind',)."""
    import src.backend.core.types.side_effect as mod

    assert mod.__all__ == ("SideEffectKind",)


def test_late_policy() -> None:
    """LatePolicy: DROP, SIDE_OUTPUT, REPROCESS."""
    from src.backend.core.types.watermark import LatePolicy

    assert LatePolicy.DROP.value == "drop"
    assert LatePolicy.SIDE_OUTPUT.value == "side_output"
    assert LatePolicy.REPROCESS.value == "reprocess"
    assert len(LatePolicy) == 3


def test_watermark_state_defaults() -> None:
    """WatermarkState defaults: current=-inf, advanced_at=0.0, late_events_total=0."""
    from src.backend.core.types.watermark import WatermarkState

    s = WatermarkState()
    assert s.current == float("-inf")
    assert s.advanced_at == 0.0
    assert s.late_events_total == 0


def test_watermark_state_advance_higher() -> None:
    """advance(new > current) → True, current обновлён, advanced_at обновлён."""
    from src.backend.core.types.watermark import WatermarkState

    s = WatermarkState()
    assert s.advance(100.0, now=50.0) is True
    assert s.current == 100.0
    assert s.advanced_at == 50.0


def test_watermark_state_advance_lower_rejected() -> None:
    """advance(new <= current) → False, state не меняется (монотонность)."""
    from src.backend.core.types.watermark import WatermarkState

    s = WatermarkState(current=100.0, advanced_at=10.0)
    assert s.advance(50.0, now=20.0) is False
    assert s.current == 100.0
    assert s.advanced_at == 10.0  # не обновляется


def test_watermark_state_advance_equal_rejected() -> None:
    """advance(new == current) → False (strict monotone)."""
    from src.backend.core.types.watermark import WatermarkState

    s = WatermarkState(current=100.0, advanced_at=10.0)
    assert s.advance(100.0, now=20.0) is False


def test_watermark_state_is_late() -> None:
    """is_late(event_time + lateness < current) → True."""
    from src.backend.core.types.watermark import WatermarkState

    s = WatermarkState(current=100.0)
    # event_time=50, no lateness: 50 < 100 → late
    assert s.is_late(50.0) is True
    # event_time=99, no lateness: 99 < 100 → late
    assert s.is_late(99.0) is True
    # event_time=100: 100 < 100 → False
    assert s.is_late(100.0) is False
    # event_time=101: 101 < 100 → False (not late, future event)
    assert s.is_late(101.0) is False


def test_watermark_state_is_late_with_allowed_lateness() -> None:
    """is_late respects allowed_lateness offset."""
    from src.backend.core.types.watermark import WatermarkState

    s = WatermarkState(current=100.0)
    # event_time=95, allowed_lateness=10 → 95+10=105, 105 < 100 → False (within lateness)
    assert s.is_late(95.0, allowed_lateness=10.0) is False
    # event_time=85, allowed_lateness=10 → 85+10=95, 95 < 100 → True
    assert s.is_late(85.0, allowed_lateness=10.0) is True


def test_watermark_state_slots() -> None:
    """WatermarkState имеет __slots__ (нет __dict__)."""
    from src.backend.core.types.watermark import WatermarkState

    s = WatermarkState()
    assert not hasattr(s, "__dict__")


def test_watermark_dunder_all() -> None:
    """__all__ = ('LatePolicy', 'WatermarkState')."""
    import src.backend.core.types.watermark as mod

    assert mod.__all__ == ("LatePolicy", "WatermarkState")


def test_invocation_command_dunder_all() -> None:
    """__all__ содержит 4 schema exports."""
    import src.backend.core.types.invocation_command as mod

    assert mod.__all__ == (
        "ActionCommandMetaSchema",
        "ActionCommandSchema",
        "InvocationOptionsSchema",
        "InvocationResultSchema",
    )
