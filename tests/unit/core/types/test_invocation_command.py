"""Tests for ``src.backend.core.types.invocation_command``.

W14.1: DTO для контракта ActionDispatcher. Pydantic v2 schemas
для InvocationOptions/Result/ActionCommand, перемещены из schemas/
в core/types для устранения layer-violation.

Тесты:
- _CoreBaseModel: extra='ignore', validate_assignment, use_enum_values
- InvocationOptionsSchema: defaults, constraints (ge=1), validator
  (delay_seconds + cron нельзя одновременно)
- InvocationResultSchema: required, defaults
- ActionCommandMetaSchema: defaults (default_factory)
- ActionCommandSchema: required action, defaults
- __all__ exports
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.enums.invocation import InvokeMode
from src.backend.core.types.invocation_command import (
    ActionCommandMetaSchema,
    ActionCommandSchema,
    InvocationOptionsSchema,
    InvocationResultSchema,
)


# ── InvocationOptionsSchema ─────────────────────────────────────────


class TestInvocationOptionsSchema:
    """Параметры исполнения action."""

    def test_minimal_construction_defaults(self) -> None:
        """Без аргументов — defaults."""
        opts = InvocationOptionsSchema()
        assert opts.mode == InvokeMode.direct
        assert opts.delay_seconds is None
        assert opts.cron is None

    def test_event_mode(self) -> None:
        opts = InvocationOptionsSchema(mode=InvokeMode.event)
        assert opts.mode == InvokeMode.event

    def test_delay_seconds_set(self) -> None:
        opts = InvocationOptionsSchema(delay_seconds=10)
        assert opts.delay_seconds == 10

    def test_cron_set(self) -> None:
        opts = InvocationOptionsSchema(cron="*/5 * * * *")
        assert opts.cron == "*/5 * * * *"

    def test_delay_seconds_ge_one_constraint(self) -> None:
        """``delay_seconds >= 1`` — 0 или negative raises."""
        with pytest.raises(ValidationError) as exc_info:
            InvocationOptionsSchema(delay_seconds=0)
        assert "delay_seconds" in str(exc_info.value)

        with pytest.raises(ValidationError):
            InvocationOptionsSchema(delay_seconds=-5)

    def test_cron_with_delay_raises(self) -> None:
        """model_validator: cron + delay_seconds нельзя одновременно."""
        with pytest.raises(ValidationError) as exc_info:
            InvocationOptionsSchema(delay_seconds=10, cron="*/5 * * * *")
        assert "cron" in str(exc_info.value) or "delay_seconds" in str(exc_info.value)

    def test_only_cron_accepted(self) -> None:
        opts = InvocationOptionsSchema(cron="0 0 * * *")
        assert opts.cron == "0 0 * * *"
        assert opts.delay_seconds is None

    def test_only_delay_accepted(self) -> None:
        opts = InvocationOptionsSchema(delay_seconds=5)
        assert opts.delay_seconds == 5
        assert opts.cron is None

    def test_validate_assignment(self) -> None:
        """``validate_assignment=True`` — assign тоже валидируется."""
        opts = InvocationOptionsSchema()
        with pytest.raises(ValidationError):
            opts.delay_seconds = 0  # type: ignore[misc]

    def test_extra_ignore(self) -> None:
        """``extra='ignore'`` — неизвестные поля silently dropped."""
        opts = InvocationOptionsSchema(unknown_field="x")  # type: ignore[call-arg]
        assert not hasattr(opts, "unknown_field")


# ── InvocationResultSchema ─────────────────────────────────────────


class TestInvocationResultSchema:
    """Унифицированный ответ для event/scheduled вызовов."""

    def test_queued(self) -> None:
        r = InvocationResultSchema(status="queued", transport="redis")
        assert r.status == "queued"
        assert r.transport == "redis"
        assert r.job_id is None
        assert r.command is None
        assert r.result is None

    def test_scheduled_with_job_id(self) -> None:
        r = InvocationResultSchema(
            status="scheduled", transport="rabbit", job_id="job-123"
        )
        assert r.status == "scheduled"
        assert r.job_id == "job-123"

    def test_completed_with_result(self) -> None:
        r = InvocationResultSchema(
            status="completed",
            transport="direct",
            result={"output": "ok"},
        )
        assert r.status == "completed"
        assert r.result == {"output": "ok"}

    def test_invalid_status_raises(self) -> None:
        """Literal["queued", "scheduled", "completed"] — другие значения rejected."""
        with pytest.raises(ValidationError):
            InvocationResultSchema(status="invalid", transport="x")  # type: ignore[arg-type]

    def test_command_field(self) -> None:
        r = InvocationResultSchema(
            status="queued",
            transport="redis",
            command={"action": "x", "payload": {}},
        )
        assert r.command == {"action": "x", "payload": {}}


# ── ActionCommandMetaSchema ────────────────────────────────────────


class TestActionCommandMetaSchema:
    """Служебные метаданные команды."""

    def test_defaults(self) -> None:
        meta = ActionCommandMetaSchema()
        assert meta.source == "http"
        assert meta.request_path is None
        assert meta.principal == ""
        assert meta.permissions == []

    def test_requested_at_default_factory(self) -> None:
        """``default_factory=lambda: datetime.now(UTC)`` — заполняется."""
        meta = ActionCommandMetaSchema()
        assert meta.requested_at is not None
        assert meta.requested_at.tzinfo is not None

    def test_requested_at_explicit(self) -> None:
        from datetime import UTC, datetime

        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        meta = ActionCommandMetaSchema(requested_at=ts)
        assert meta.requested_at == ts

    def test_request_path_set(self) -> None:
        meta = ActionCommandMetaSchema(request_path="/api/v1/test")
        assert meta.request_path == "/api/v1/test"

    def test_principal_and_permissions(self) -> None:
        meta = ActionCommandMetaSchema(
            principal="user-123",
            permissions=["read", "write"],
        )
        assert meta.principal == "user-123"
        assert meta.permissions == ["read", "write"]

    def test_permissions_default_factory_isolation(self) -> None:
        """Каждый инстанс получает свой list."""
        m1 = ActionCommandMetaSchema()
        m2 = ActionCommandMetaSchema()
        m1.permissions.append("x")
        assert m2.permissions == []


# ── ActionCommandSchema ────────────────────────────────────────────


class TestActionCommandSchema:
    """Универсальная команда для event bus."""

    def test_minimal_construction(self) -> None:
        cmd = ActionCommandSchema(action="credit.score.calculate")
        assert cmd.action == "credit.score.calculate"
        assert cmd.payload == {}
        assert isinstance(cmd.meta, ActionCommandMetaSchema)

    def test_payload_default(self) -> None:
        cmd = ActionCommandSchema(action="x")
        assert cmd.payload == {}

    def test_payload_set(self) -> None:
        cmd = ActionCommandSchema(
            action="x",
            payload={"key": "value", "count": 42},
        )
        assert cmd.payload == {"key": "value", "count": 42}

    def test_meta_explicit(self) -> None:
        meta = ActionCommandMetaSchema(source="cli", principal="admin")
        cmd = ActionCommandSchema(action="x", meta=meta)
        assert cmd.meta.source == "cli"
        assert cmd.meta.principal == "admin"

    def test_missing_action_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ActionCommandSchema()  # type: ignore[call-arg]
        assert "action" in str(exc_info.value)


# ── __all__ exports ─────────────────────────────────────────────────


class TestInvocationCommandExports:
    """``__all__`` exports."""

    def test_exports(self) -> None:
        from src.backend.core.types import invocation_command

        assert set(invocation_command.__all__) == {
            "ActionCommandMetaSchema",
            "ActionCommandSchema",
            "InvocationOptionsSchema",
            "InvocationResultSchema",
        }
