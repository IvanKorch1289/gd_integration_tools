"""Secret rotation Protocol + audit hooks.

Wave: ``[wave:s16/k1-w3-vault-rotation-protocol]`` — DoD-8 Sprint 16.

Назначение: единый контракт для rotation-сервисов (Vault/AWS Secrets
Manager/HCP/...). Реальная имплементация поверх ``hvac`` живёт в
``infrastructure/secrets/`` (защищённая директория). Этот модуль —
domain-agnostic API в ``core/security/``, который можно безопасно
использовать в callers (services/middleware) без зависимости от
конкретного backend.

Контракт обеспечивает:

1. Async rotate(secret_path) с idempotency через token.
2. Audit-event ``secret.rotated`` с correlation_id (обязательно).
3. Integration с TaskRegistry — фоновая ротация через зарегистрированную
   задачу с deadline_seconds (см. infrastructure/observability/watchdog).
4. Default-OFF feature-flag ``secrets_rotation_enabled`` (rollout).

Carryover S17:
* Реальный wire с ``hvac`` Vault client (capability secrets.rotate).
* Подключение CronCreate-job для periodic-rotation по schedule.
* Подключение audit-sink в [AuditService] (S16 К2 W8 finale).
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

__all__ = (
    "AuditableRotator",
    "FakeRotator",
    "RotationAuditEvent",
    "RotationResult",
    "SecretRotator",
)

_logger = get_logger("core.security.secret_rotation")

#: Async callable для записи audit-event. Получает событие как dict.
AuditSink = Callable[["RotationAuditEvent"], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RotationResult:
    """Результат rotation для одного secret-path.

    Attributes:
        secret_path: KV-путь, который был ротирован.
        rotation_id: UUID операции (для трассировки и idempotency).
        rotated_at: Время завершения rotation в UTC.
        new_version: Новый номер версии в Vault KV v2 (если backend
            поддерживает versioning); ``None`` при недоступности метаданных.
    """

    secret_path: str
    rotation_id: str
    rotated_at: datetime
    new_version: int | None


@dataclass(frozen=True, slots=True)
class RotationAuditEvent:
    """Audit-event ``secret.rotated`` — для записи в audit-sink/trail.

    Attributes:
        event_id: UUID события.
        secret_path: Путь, который был ротирован.
        rotation_id: Идентификатор rotation-операции.
        correlation_id: Распространённый correlation_id (request/tenant/...).
        rotated_at: Время в UTC.
        actor: Кто инициировал (system/cron/user@id).
        outcome: ``success`` | ``failure``.
        error_class: Имя класса исключения при failure (или None).
    """

    event_id: str
    secret_path: str
    rotation_id: str
    correlation_id: str | None
    rotated_at: datetime
    actor: str
    outcome: str
    error_class: str | None


@runtime_checkable
class SecretRotator(Protocol):
    """Контракт rotation-сервиса.

    Реализация обязана:

    1. Быть idempotent: повторный ``rotate(path)`` с тем же ``rotation_id``
       не должен сбоить (либо возвращает прежний результат, либо повторяет
       safely).
    2. Вызывать ``audit_sink`` при ``rotate`` с outcome=success/failure.
    3. Не выполнять операции в blocking-режиме: только async.
    """

    async def rotate(
        self,
        secret_path: str,
        *,
        correlation_id: str | None = None,
        actor: str = "system",
    ) -> RotationResult:
        """Выполнить rotation одного secret-path.

        Args:
            secret_path: KV-путь (например, ``secret/data/api/token``).
            correlation_id: Для трассировки; прокидывается в audit-event.
            actor: Инициатор операции (для audit).

        Returns:
            RotationResult с rotation_id и (при наличии) new_version.

        Raises:
            Произвольное исключение от backend — caller отвечает за
            обработку; audit_sink уже получил event с outcome=failure.
        """


class AuditableRotator:
    """Wrapper, добавляющий audit-event + retry hook к произвольному [SecretRotator].

    Использование (production)::

        inner = VaultHvacRotator(...)           # infrastructure-импл
        rotator = AuditableRotator(
            inner=inner,
            audit_sink=audit_service.write,
            feature_enabled=lambda: settings.secrets_rotation_enabled,
        )
        await rotator.rotate("secret/data/api/token", correlation_id=ctx.correlation_id)

    При выключенном feature-flag — ``rotate`` бросает
    :class:`RuntimeError` с кодом ``rotation_disabled``.
    """

    def __init__(
        self,
        *,
        inner: SecretRotator,
        audit_sink: AuditSink,
        feature_enabled: Callable[[], bool] | None = None,
    ) -> None:
        """Создать wrapper.

        Args:
            inner: Реальный rotator (Vault/AWS/...).
            audit_sink: Async-callable для записи RotationAuditEvent.
            feature_enabled: Lambda, возвращающая текущий статус
                feature-flag ``secrets_rotation_enabled``. None = always on.
        """
        self._inner = inner
        self._audit_sink = audit_sink
        self._feature_enabled = feature_enabled or (lambda: True)

    async def rotate(
        self,
        secret_path: str,
        *,
        correlation_id: str | None = None,
        actor: str = "system",
    ) -> RotationResult:
        """Выполнить ротацию с audit-event + feature-gate.

        Args:
            secret_path: KV-путь.
            correlation_id: Для трассировки.
            actor: Инициатор.

        Returns:
            RotationResult от inner-rotator.

        Raises:
            RuntimeError: при выключенном feature-flag (rotation_disabled).
            Exception: пробрасывает исключения inner-rotator (после audit).
        """
        if not self._feature_enabled():
            _logger.warning(
                "secret rotation skipped: feature flag off path=%s", secret_path
            )
            raise RuntimeError("rotation_disabled")

        try:
            result = await self._inner.rotate(
                secret_path, correlation_id=correlation_id, actor=actor
            )
        except Exception as exc:
            await self._emit_audit(
                secret_path=secret_path,
                rotation_id="-",
                correlation_id=correlation_id,
                actor=actor,
                outcome="failure",
                error_class=type(exc).__name__,
            )
            raise
        await self._emit_audit(
            secret_path=secret_path,
            rotation_id=result.rotation_id,
            correlation_id=correlation_id,
            actor=actor,
            outcome="success",
            error_class=None,
        )
        return result

    async def _emit_audit(
        self,
        *,
        secret_path: str,
        rotation_id: str,
        correlation_id: str | None,
        actor: str,
        outcome: str,
        error_class: str | None,
    ) -> None:
        """Сформировать и отправить audit-event."""
        event = RotationAuditEvent(
            event_id=uuid.uuid4().hex,
            secret_path=secret_path,
            rotation_id=rotation_id,
            correlation_id=correlation_id,
            rotated_at=datetime.now(UTC),
            actor=actor,
            outcome=outcome,
            error_class=error_class,
        )
        try:
            await self._audit_sink(event)
        except Exception as exc:
            _logger.error(
                "secret rotation audit-sink failed path=%s rotation_id=%s error=%s",
                secret_path,
                rotation_id,
                repr(exc),
            )


class FakeRotator:
    """In-memory реализация [SecretRotator] для тестов и default-OFF.

    Хранит счётчик ротаций по path; new_version = счётчик. Полезна для
    unit-тестов AuditableRotator и в dev_light до подключения реального
    Vault backend.
    """

    def __init__(self) -> None:
        """Инициализация пустого счётчика."""
        self._counters: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def rotate(
        self,
        secret_path: str,
        *,
        correlation_id: str | None = None,
        actor: str = "system",
    ) -> RotationResult:
        """Ротация с инкрементом счётчика — см. [SecretRotator.rotate]."""
        del correlation_id, actor  # FakeRotator не использует
        async with self._lock:
            self._counters[secret_path] = self._counters.get(secret_path, 0) + 1
            version = self._counters[secret_path]
        return RotationResult(
            secret_path=secret_path,
            rotation_id=uuid.uuid4().hex,
            rotated_at=datetime.now(UTC),
            new_version=version,
        )
