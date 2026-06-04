"""Unit-тесты DeferredExecutionMixin (S39 W5 — Airflow-style scheduling).

Покрытие:
    * ``defer_for(seconds)`` — set ``_deferred`` (default 60s).
    * ``schedule(cron)`` — parse + validate cron expression.
    * ``defer_until(timestamp)`` — datetime / ISO string / unix int / unix float.
    * ``defer_if(condition)`` — conditional defer; not evaluated at build time.
    * ``cancel_deferred()`` — clears ``_deferred``.
    * Validation: invalid cron / negative seconds / invalid timestamp.
    * Chainability: all methods return ``self`` (builder).
    * NO-OP at build time: state set in ``_deferred``, не в ``_processors``.
    * MRO integration: ``DeferredExecutionMixin`` в MRO ``RouteBuilder``.
    * Multi-call semantics: последний вызов перезаписывает state.
    * Per-builder isolation: разные builders — разный ``_deferred``.
    * Integration with simple route (build → metadata).
"""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.deferred_execution_mixin import (
    DEFAULT_DELAY_SECONDS,
    DeferredExecutionMixin,
    _coerce_timestamp,
    _validate_cron_expression,
)

# ── Fixtures ──


@pytest.fixture
def builder() -> RouteBuilder:
    return RouteBuilder.from_("test_route", source="internal:test")


@pytest.fixture
def fresh_builder() -> RouteBuilder:
    """Свежий builder с пустым ``_deferred`` (после инициализации)."""
    return RouteBuilder.from_("fresh", source="t")


# ── Internal helpers ──


class TestInternalHelpers:
    """Тесты для module-private утилит (``_validate_cron_expression``,
    ``_coerce_timestamp``)."""

    def test_validate_cron_5_fields(self) -> None:
        assert _validate_cron_expression("0 * * * *") == "0 * * * *"

    def test_validate_cron_6_fields(self) -> None:
        # 6-полевой (sec min hour dom mon dow)
        assert _validate_cron_expression("0 0 * * * *") == "0 0 * * * *"

    def test_validate_cron_strip_whitespace(self) -> None:
        assert _validate_cron_expression("  0 * * * *  ") == "0 * * * *"

    def test_validate_cron_invalid_field_count(self) -> None:
        with pytest.raises(ValueError, match="5 or 6 fields"):
            _validate_cron_expression("0 * * *")  # 4 fields

    def test_validate_cron_invalid_value(self) -> None:
        with pytest.raises(ValueError, match="5 or 6 fields"):
            _validate_cron_expression("0 * *")

    def test_validate_cron_empty_string(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_cron_expression("")

    def test_validate_cron_non_string(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_cron_expression(123)  # type: ignore[arg-type]

    def test_coerce_datetime_naive(self) -> None:
        naive = datetime(2026, 12, 31, 23, 59, 59)
        result = _coerce_timestamp(naive)
        expected = naive.replace(tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_coerce_datetime_aware(self) -> None:
        from zoneinfo import ZoneInfo

        moscow = ZoneInfo("Europe/Moscow")
        aware = datetime(2026, 12, 31, 23, 59, 59, tzinfo=moscow)
        result = _coerce_timestamp(aware)
        # Moscow is UTC+3, so 23:59:59 MSK = 20:59:59 UTC
        expected = aware.astimezone(timezone.utc).timestamp()
        assert result == expected

    def test_coerce_iso_string_with_tz(self) -> None:
        result = _coerce_timestamp("2026-12-31T23:59:59+00:00")
        expected = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_coerce_iso_string_naive(self) -> None:
        result = _coerce_timestamp("2026-12-31T23:59:59")
        expected = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_coerce_iso_string_with_whitespace(self) -> None:
        result = _coerce_timestamp("  2026-12-31T23:59:59  ")
        expected = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_coerce_unix_int(self) -> None:
        assert _coerce_timestamp(1234567890) == 1234567890.0

    def test_coerce_unix_float(self) -> None:
        assert _coerce_timestamp(1234567890.5) == 1234567890.5

    def test_coerce_bool_raises(self) -> None:
        with pytest.raises(TypeError, match="bool is not a valid timestamp"):
            _coerce_timestamp(True)  # type: ignore[arg-type]

    def test_coerce_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot parse ISO-8601"):
            _coerce_timestamp("not-a-date")

    def test_coerce_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="empty string"):
            _coerce_timestamp("   ")

    def test_coerce_unsupported_type_raises(self) -> None:
        with pytest.raises(TypeError, match="unsupported type"):
            _coerce_timestamp([2026, 12, 31])  # type: ignore[arg-type]


# ── defer_for ──


class TestDeferFor:
    def test_defer_for_basic(self, builder: RouteBuilder) -> None:
        b = builder.defer_for(seconds=120)
        assert b._deferred == {
            "type": "delay",
            "seconds": 120,
            "scheduled_at": pytest.approx(builder._deferred.get("scheduled_at", 0)),
        }
        assert b._deferred["type"] == "delay"
        assert b._deferred["seconds"] == 120

    def test_defer_for_default(self, builder: RouteBuilder) -> None:
        b = builder.defer_for()
        assert b._deferred["seconds"] == DEFAULT_DELAY_SECONDS
        assert b._deferred["seconds"] == 60

    def test_defer_for_zero(self, builder: RouteBuilder) -> None:
        b = builder.defer_for(seconds=0)
        assert b._deferred["seconds"] == 0
        assert b._deferred["type"] == "delay"

    def test_defer_for_negative_raises(self, builder: RouteBuilder) -> None:
        with pytest.raises(ValueError, match="seconds must be >= 0"):
            builder.defer_for(seconds=-1)

    def test_defer_for_non_int_raises(self, builder: RouteBuilder) -> None:
        with pytest.raises(TypeError, match="seconds must be int"):
            builder.defer_for(seconds=1.5)  # type: ignore[arg-type]

    def test_defer_for_bool_raises(self, builder: RouteBuilder) -> None:
        with pytest.raises(TypeError, match="seconds must be int"):
            builder.defer_for(seconds=True)  # type: ignore[arg-type]

    def test_defer_for_chainable(self, builder: RouteBuilder) -> None:
        result = builder.defer_for(seconds=30)
        assert result is builder


# ── schedule (cron) ──


class TestSchedule:
    def test_schedule_basic_cron(self, builder: RouteBuilder) -> None:
        b = builder.schedule(cron="0 * * * *")
        assert b._deferred["type"] == "cron"
        assert b._deferred["expression"] == "0 * * * *"
        assert b._deferred["timezone"] == "UTC"

    def test_schedule_with_timezone(self, builder: RouteBuilder) -> None:
        b = builder.schedule(cron="0 9 * * *", timezone_name="Europe/Moscow")
        assert b._deferred["timezone"] == "Europe/Moscow"

    def test_schedule_invalid_cron_raises(self, builder: RouteBuilder) -> None:
        with pytest.raises(ValueError, match="5 or 6 fields"):
            builder.schedule(cron="0 * *")

    def test_schedule_wrong_field_count_raises(self, builder: RouteBuilder) -> None:
        with pytest.raises(ValueError, match="5 or 6 fields"):
            builder.schedule(cron="0 * *")  # only 3 fields

    def test_schedule_6_field_cron(self, builder: RouteBuilder) -> None:
        # 6-полевой cron (sec min hour dom mon dow)
        b = builder.schedule(cron="30 0 * * * *")
        assert b._deferred["expression"] == "30 0 * * * *"

    def test_schedule_chainable(self, builder: RouteBuilder) -> None:
        result = builder.schedule(cron="*/5 * * * *")
        assert result is builder


# ── defer_until ──


class TestDeferUntil:
    def test_defer_until_datetime(self, builder: RouteBuilder) -> None:
        target = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        b = builder.defer_until(target)
        assert b._deferred["type"] == "until"
        assert b._deferred["timestamp"] == target.timestamp()

    def test_defer_until_iso_string(self, builder: RouteBuilder) -> None:
        b = builder.defer_until("2026-12-31T23:59:59")
        expected = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert b._deferred["timestamp"] == expected

    def test_defer_until_unix_int(self, builder: RouteBuilder) -> None:
        b = builder.defer_until(1234567890)
        assert b._deferred["timestamp"] == 1234567890.0

    def test_defer_until_unix_float(self, builder: RouteBuilder) -> None:
        b = builder.defer_until(1234567890.5)
        assert b._deferred["timestamp"] == 1234567890.5

    def test_defer_until_naive_datetime_treated_as_utc(
        self, builder: RouteBuilder
    ) -> None:
        naive = datetime(2026, 6, 1, 12, 0, 0)  # no tz
        b = builder.defer_until(naive)
        expected = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        assert b._deferred["timestamp"] == expected

    def test_defer_until_aware_datetime_converted_to_utc(
        self, builder: RouteBuilder
    ) -> None:
        from zoneinfo import ZoneInfo

        moscow = ZoneInfo("Europe/Moscow")
        aware = datetime(2026, 6, 1, 15, 0, 0, tzinfo=moscow)  # 12:00 UTC
        b = builder.defer_until(aware)
        expected = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        assert b._deferred["timestamp"] == expected

    def test_defer_until_invalid_string_raises(self, builder: RouteBuilder) -> None:
        with pytest.raises(ValueError, match="cannot parse ISO-8601"):
            builder.defer_until("not-a-date")

    def test_defer_until_unsupported_type_raises(self, builder: RouteBuilder) -> None:
        with pytest.raises(TypeError, match="unsupported type"):
            builder.defer_until([2026, 12, 31])  # type: ignore[arg-type]

    def test_defer_until_chainable(self, builder: RouteBuilder) -> None:
        result = builder.defer_until(1234567890)
        assert result is builder


# ── defer_if ──


class TestDeferIf:
    def test_defer_if_callable_stored(self, builder: RouteBuilder) -> None:
        cond = lambda ex: True  # noqa: E731
        b = builder.defer_if(cond)
        assert b._deferred["type"] == "conditional"
        assert b._deferred["condition"] is cond
        # Условие НЕ вызывается at build time (no exchange context)
        # — вызов произойдёт в runtime.

    def test_defer_if_non_callable_raises(self, builder: RouteBuilder) -> None:
        with pytest.raises(TypeError, match="condition must be callable"):
            builder.defer_if("not a function")  # type: ignore[arg-type]

    def test_defer_if_chainable(self, builder: RouteBuilder) -> None:
        result = builder.defer_if(lambda ex: True)
        assert result is builder


# ── cancel_deferred ──


class TestCancelDeferred:
    def test_cancel_deferred_clears_state(self, builder: RouteBuilder) -> None:
        builder.defer_for(seconds=60)
        assert builder._deferred != {}
        builder.cancel_deferred()
        assert builder._deferred == {}

    def test_cancel_deferred_no_op_when_empty(self, builder: RouteBuilder) -> None:
        # Should not raise even if _deferred is empty
        builder.cancel_deferred()
        assert builder._deferred == {}

    def test_cancel_deferred_chainable(self, builder: RouteBuilder) -> None:
        result = builder.cancel_deferred()
        assert result is builder

    def test_cancel_then_set_new(self, builder: RouteBuilder) -> None:
        builder.defer_for(seconds=30)
        builder.cancel_deferred()
        builder.schedule(cron="0 * * * *")
        assert builder._deferred["type"] == "cron"


# ── Builder integration ──


class TestBuilderIntegration:
    def test_mixin_in_mro(self, builder: RouteBuilder) -> None:
        mro_names = [c.__name__ for c in type(builder).__mro__]
        assert "DeferredExecutionMixin" in mro_names

    def test_mixin_module_exports(self) -> None:
        from src.backend.dsl.builders import deferred_execution_mixin as mod

        assert "DeferredExecutionMixin" in mod.__all__
        assert mod.DeferredExecutionMixin is DeferredExecutionMixin

    def test_no_op_at_build_time(self, builder: RouteBuilder) -> None:
        """Methods only mutate ``_deferred``; ``_processors`` остаётся пустым."""
        builder.defer_for(seconds=60)
        builder.schedule(cron="0 * * * *")
        builder.defer_until(1234567890)
        builder.defer_if(lambda ex: True)
        # _deferred — set (последний вызов: defer_if → "conditional")
        assert builder._deferred["type"] == "conditional"
        # _processors — НЕ затронут (build-time is NO-OP)
        assert builder._processors == []

    def test_build_succeeds_with_deferred(self, builder: RouteBuilder) -> None:
        """``build()`` не падает с deferred state — это просто metadata."""
        builder.defer_for(seconds=60)
        builder.cancel_deferred()  # очищаем, чтобы build был тривиальным
        pipeline = builder.build()
        assert pipeline is not None

    def test_mixin_with_real_route(self, builder: RouteBuilder) -> None:
        """End-to-end: chain defer_for + .log() + cancel_deferred → build."""
        builder.defer_for(seconds=30).log().cancel_deferred()
        pipeline = builder.build()
        assert pipeline is not None
        # 1 процессор (log); deferred cleared before build
        assert len(pipeline.processors) == 1

    def test_multi_call_last_wins(self, builder: RouteBuilder) -> None:
        """Последний defer-вызов перезаписывает ``_deferred``."""
        builder.defer_for(seconds=30)
        builder.schedule(cron="0 * * * *")
        assert builder._deferred["type"] == "cron"
        builder.defer_until(1234567890)
        assert builder._deferred["type"] == "until"

    def test_per_builder_isolation(self) -> None:
        b1 = RouteBuilder.from_("r1", source="t")
        b2 = RouteBuilder.from_("r2", source="t")
        b1.defer_for(seconds=10)
        b2.defer_for(seconds=999)
        assert b1._deferred["seconds"] == 10
        assert b2._deferred["seconds"] == 999

    def test_full_chain(self, builder: RouteBuilder) -> None:
        """Fluent chain: defer_for + cancel + schedule — all chainable."""
        result = (
            builder.defer_for(seconds=60)
            .cancel_deferred()
            .schedule(cron="*/10 * * * *")
        )
        assert result is builder
        assert result._deferred["type"] == "cron"
        assert result._deferred["expression"] == "*/10 * * * *"


# ── Module-level API ──


class TestModuleAPI:
    def test_default_delay_seconds_constant(self) -> None:
        assert DEFAULT_DELAY_SECONDS == 60

    def test_mixin_has_expected_methods(self) -> None:
        expected = {
            "defer_for",
            "schedule",
            "defer_until",
            "defer_if",
            "cancel_deferred",
        }
        for name in expected:
            assert hasattr(DeferredExecutionMixin, name), f"Missing method: {name}"
            assert callable(getattr(DeferredExecutionMixin, name))
