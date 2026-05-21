"""Unit-тесты Protocol secret_rotation + AuditableRotator + FakeRotator.

Wave: ``[wave:s16/k1-w3-vault-rotation-protocol]`` — DoD-8 Sprint 16.

Покрытие:
* FakeRotator: счётчик по path, new_version инкрементируется.
* AuditableRotator: success → audit-event с outcome=success.
* AuditableRotator: failure → audit-event с error_class, исключение
  пробрасывается caller'у.
* feature_enabled=False → RuntimeError('rotation_disabled') без inner.
* Audit-sink ошибка не должна сорвать основной flow.
"""

from __future__ import annotations

import pytest

from src.backend.core.security.secret_rotation import (
    AuditableRotator,
    FakeRotator,
    RotationAuditEvent,
    RotationResult,
    SecretRotator,
)


@pytest.mark.asyncio
async def test_fake_rotator_increments_version() -> None:
    """FakeRotator повышает new_version при повторной ротации."""
    rotator = FakeRotator()
    first = await rotator.rotate("secret/api/token")
    second = await rotator.rotate("secret/api/token")
    third = await rotator.rotate("secret/db/password")
    assert first.new_version == 1
    assert second.new_version == 2
    assert third.new_version == 1  # другой path — отдельный счётчик
    assert first.rotation_id != second.rotation_id


@pytest.mark.asyncio
async def test_fake_rotator_implements_protocol() -> None:
    """FakeRotator структурально удовлетворяет [SecretRotator] Protocol."""
    rotator = FakeRotator()
    assert isinstance(rotator, SecretRotator)


@pytest.mark.asyncio
async def test_auditable_rotator_emits_success_event() -> None:
    """Successful rotation → audit-event с outcome=success."""
    events: list[RotationAuditEvent] = []

    async def sink(ev: RotationAuditEvent) -> None:
        events.append(ev)

    rotator = AuditableRotator(inner=FakeRotator(), audit_sink=sink)
    result = await rotator.rotate(
        "secret/api/token", correlation_id="cid-1", actor="cron"
    )
    assert isinstance(result, RotationResult)
    assert len(events) == 1
    ev = events[0]
    assert ev.outcome == "success"
    assert ev.secret_path == "secret/api/token"
    assert ev.correlation_id == "cid-1"
    assert ev.actor == "cron"
    assert ev.error_class is None
    assert ev.rotation_id == result.rotation_id


@pytest.mark.asyncio
async def test_auditable_rotator_emits_failure_event_and_reraises() -> None:
    """При исключении inner → audit failure + пробросить исключение."""
    events: list[RotationAuditEvent] = []

    async def sink(ev: RotationAuditEvent) -> None:
        events.append(ev)

    class _FailingRotator:
        async def rotate(self, secret_path: str, **kwargs: object) -> RotationResult:
            raise PermissionError("Vault token rejected")

    rotator = AuditableRotator(inner=_FailingRotator(), audit_sink=sink)
    with pytest.raises(PermissionError):
        await rotator.rotate("secret/api/token", correlation_id="cid-2")

    assert len(events) == 1
    assert events[0].outcome == "failure"
    assert events[0].error_class == "PermissionError"
    assert events[0].correlation_id == "cid-2"


@pytest.mark.asyncio
async def test_auditable_rotator_feature_flag_off_raises() -> None:
    """При feature-flag=False → RuntimeError('rotation_disabled') без audit."""
    events: list[RotationAuditEvent] = []

    async def sink(ev: RotationAuditEvent) -> None:
        events.append(ev)

    rotator = AuditableRotator(
        inner=FakeRotator(),
        audit_sink=sink,
        feature_enabled=lambda: False,
    )
    with pytest.raises(RuntimeError, match="rotation_disabled"):
        await rotator.rotate("secret/api/token")
    # Audit-event НЕ должен возникнуть (rotation не происходил).
    assert events == []


@pytest.mark.asyncio
async def test_audit_sink_failure_does_not_break_caller() -> None:
    """Если audit-sink упал — основной поток не должен страдать.

    Для success-кейса: result всё равно возвращается. Sink-error
    логируется (см. модуль), но не пробрасывается.
    """

    async def failing_sink(ev: RotationAuditEvent) -> None:
        raise IOError("audit log unavailable")

    rotator = AuditableRotator(inner=FakeRotator(), audit_sink=failing_sink)
    # Не должно бросить — sink-error поглощается с log.
    result = await rotator.rotate("secret/api/token")
    assert result.secret_path == "secret/api/token"


@pytest.mark.asyncio
async def test_auditable_rotator_defaults_actor_to_system() -> None:
    """По умолчанию actor=system в audit-event."""
    events: list[RotationAuditEvent] = []

    async def sink(ev: RotationAuditEvent) -> None:
        events.append(ev)

    rotator = AuditableRotator(inner=FakeRotator(), audit_sink=sink)
    await rotator.rotate("secret/api/token")
    assert events[0].actor == "system"
