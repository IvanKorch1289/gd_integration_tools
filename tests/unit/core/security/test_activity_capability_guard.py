"""Тесты capability guard для Temporal activities (Sprint 4 Wave E)."""
# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.security.activity_capability_guard import (
    CapabilityContext,
    CapabilityDeniedError,
    capability_guarded_activity,
    get_active_capability_context,
    set_active_capability_context,
)


@pytest.fixture(autouse=True)
def _reset_context() -> Any:
    """Сбрасывает активный capability-контекст между тестами."""
    set_active_capability_context(None)
    yield
    set_active_capability_context(None)


def _build_context(
    *, deny: tuple[str, ...] = (), audit: Any = None
) -> CapabilityContext:
    """Сконструировать тестовый CapabilityContext с mock-gate.

    Если capability входит в ``deny`` — gate бросает CapabilityDeniedError.
    """
    gate = MagicMock()

    def _check(plugin: str, capability: str, scope: str | None) -> None:
        if capability in deny:
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
            )

    gate.check.side_effect = _check
    return CapabilityContext(
        plugin_name="test-plugin", gate=gate, scope=None, audit=audit
    )


def test_capability_check_passes_when_granted(monkeypatch: pytest.MonkeyPatch) -> None:
    """При наличии всех capability — activity выполняется без exception."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.activity_capability_gate_enabled",
        True,
    )
    context = _build_context()
    set_active_capability_context(context)

    @capability_guarded_activity(("db.read",))
    async def my_activity(value: int) -> int:
        return value * 2

    assert asyncio.run(my_activity(21)) == 42
    context.gate.check.assert_called_once_with("test-plugin", "db.read", None)


def test_capability_denied_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """При отсутствии capability — поднимается CapabilityDeniedError."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.activity_capability_gate_enabled",
        True,
    )
    set_active_capability_context(_build_context(deny=("db.write",)))

    @capability_guarded_activity(("db.write",))
    async def my_activity() -> int:
        return 1

    with pytest.raises(CapabilityDeniedError):
        asyncio.run(my_activity())


def test_audit_event_emitted_on_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    """При deny audit-callback получает event 'activity.capability.denied'."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.activity_capability_gate_enabled",
        True,
    )
    audit_events: list[dict[str, object]] = []
    set_active_capability_context(
        _build_context(deny=("net.outbound.x",), audit=audit_events.append)
    )

    @capability_guarded_activity(("net.outbound.x",))
    async def my_activity() -> int:
        return 1

    with pytest.raises(CapabilityDeniedError):
        asyncio.run(my_activity())

    assert any(ev.get("event") == "activity.capability.denied" for ev in audit_events)


def test_disabled_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """При выключенном feature-flag — capability-проверка пропускается."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.activity_capability_gate_enabled",
        False,
    )
    set_active_capability_context(_build_context(deny=("db.read",)))

    @capability_guarded_activity(("db.read",))
    async def my_activity() -> int:
        return 99

    # Должно выполниться, несмотря на deny — flag выключен.
    assert asyncio.run(my_activity()) == 99


def test_no_context_failopen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без активного контекста (legacy) — fail-open, activity выполняется."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.activity_capability_gate_enabled",
        True,
    )
    # set_active_capability_context(None) уже в fixture.

    @capability_guarded_activity(("db.read",))
    async def my_activity() -> str:
        return "ok"

    assert asyncio.run(my_activity()) == "ok"


def test_empty_capabilities_returns_identity() -> None:
    """Пустой кортеж capabilities → identity-декоратор (без обёртки)."""

    async def my_activity() -> int:
        return 7

    wrapped = capability_guarded_activity(())(my_activity)
    assert wrapped is my_activity


def test_get_set_context_roundtrip() -> None:
    """set/get capability-контекста работает корректно."""
    context = _build_context()
    assert get_active_capability_context() is None
    set_active_capability_context(context)
    assert get_active_capability_context() is context
    set_active_capability_context(None)
    assert get_active_capability_context() is None


def test_dual_emit_calls_both_callback_and_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S109 W1: dual-emit — callback + emit_audit (canonical).

    Verifies that ``_emit_audit`` emits BOTH the legacy callback
    (for backward compat) AND the canonical facade helper (for
    unified audit service).
    """
    from src.backend.core.security.activity_capability_guard import _emit_audit

    events: list[dict[str, object]] = []

    def audit_cb(event: dict[str, object]) -> None:
        events.append(event)

    facade_calls: list[dict[str, object]] = []

    def fake_emit_audit(
        *,
        event: str,
        actor: str = "system",
        resource: str = "",
        action: str = "",
        outcome: str = "success",
        details: dict[str, Any] | None = None,
    ) -> None:
        facade_calls.append(
            {
                "event": event,
                "actor": actor,
                "resource": resource,
                "action": action,
                "outcome": outcome,
                "details": details,
            }
        )

    monkeypatch.setattr("src.backend.core.audit.facade.emit_audit", fake_emit_audit)

    context = _build_context()
    context.audit = audit_cb
    test_event: dict[str, object] = {
        "event": "activity.capability.denied",
        "plugin": "test_plugin",
        "capability": "db.read",
        "activity": "my_activity",
    }
    _emit_audit(context, test_event)

    # Legacy callback received event
    assert len(events) == 1
    assert events[0]["event"] == "activity.capability.denied"
    # Canonical facade was also called
    assert len(facade_calls) == 1
    assert facade_calls[0]["event"] == "activity.capability.denied"
    assert facade_calls[0]["actor"] == "test_plugin"
    assert facade_calls[0]["outcome"] == "denied"
    assert facade_calls[0]["resource"] == "my_activity"
