"""Audit HMAC-chain verify lifecycle — periodic tamper-detection runner (FIX-H5).

Wire'ит периодический вызов :meth:`ImmutableAuditStore.verify` в background
asyncio-задачу через :class:`TaskRegistry`. ``verify()`` проходит по всей
HMAC-цепочке ``audit_log_immutable`` и детектирует tampering (удаление /
редактирование / подмену ключа). Без этого периодического вызова HMAC-chain
**формально существует, но tamper detection нефункционален** (H5).

Архитектурные принципы (mirror :mod:`infrastructure.messaging.dlq.cleanup_lifecycle`):

* Task registered в :class:`TaskRegistry` → graceful shutdown через
  ``TaskRegistry.shutdown_all()`` (вызывается в ``shutdown.py``).
* Никаких ``time.sleep`` — только ``asyncio.sleep``.
* Итерация никогда не валит loop: ошибки логируются (best-effort).
* Opt-in через ``feature_flags.audit_hmac_verify_enabled`` (default False для
  dev/dev_light, True в prod).

Использование::

    from src.backend.infrastructure.observability.audit_verify_lifecycle import (
        start_audit_verify,
        stop_audit_verify,
        try_start_default,
    )

    await start_audit_verify(store=immutable_audit_store, interval_hours=24.0)
    # On shutdown:
    await stop_audit_verify()

В startup hook (best-effort)::

    from src.backend.infrastructure.observability.audit_verify_lifecycle import (
        try_start_default,
    )

    await try_start_default(session_factory=db.get_session, interval_hours=24.0)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.backend.infrastructure.observability.immutable_audit import (
        ImmutableAuditStore,
    )

__all__ = (
    "AuditVerifyScheduler",
    "default_scheduler",
    "start_audit_verify",
    "stop_audit_verify",
    "try_start_default",
)

_logger = get_logger("observability.audit_verify_lifecycle")


class AuditVerifyScheduler:
    """Background-цикл для periodic HMAC-chain verify (tamper detection).

    Args:
        store: :class:`ImmutableAuditStore` (поверх Postgres session_factory).
        interval_hours: период запуска verify() (default 24h).

    """

    def __init__(
        self, *, store: ImmutableAuditStore, interval_hours: float = 24.0
    ) -> None:
        if interval_hours <= 0:
            raise ValueError("interval_hours должен быть > 0")
        self._store = store
        self._interval_seconds = interval_hours * 3600.0
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._runs_total: int = 0

    @property
    def interval_seconds(self) -> float:
        """Вернуть интервал verify-цикла в секундах."""
        return self._interval_seconds

    @property
    def is_running(self) -> bool:
        """Вернуть ``True`` если background-цикл активен."""
        return self._running

    @property
    def runs_total(self) -> int:
        """Вернуть общее количество выполненных verify-итераций."""
        return self._runs_total

    async def start(self) -> None:
        """Зарегистрировать background-task в TaskRegistry."""
        if self._running:
            return
        self._running = True
        self._task = get_task_registry().create_task(
            self._loop(), name="audit-hmac-verify"
        )
        _logger.info(
            "AuditVerifyScheduler started (interval=%.1fh)",
            self._interval_seconds / 3600.0,
        )

    async def stop(self) -> None:
        """Graceful shutdown с отменой background-task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("AuditVerifyScheduler stopped")

    async def _loop(self) -> None:
        """Periodic verify loop — никогда не валится (ловит все исключения).

        Best-effort: положительный результат логируется на INFO,
        обнаруженный tampering — на ERROR (должен триггерить alerting),
        любые ошибки verify (например, БД недоступна) — на WARNING.
        """
        while self._running:
            try:
                result = await self._store.verify()
                self._runs_total += 1
                if result.valid:
                    _logger.info(
                        "audit HMAC-chain verify OK: %s (checked=%d, run #%d)",
                        result.details,
                        result.total_checked,
                        self._runs_total,
                    )
                else:
                    # Tampering detected — критический сигнал для SOC/SIEM.
                    _logger.error(
                        "audit HMAC-chain TAMPER DETECTED: %s "
                        "(first_broken_seq=%s, checked=%d, run #%d)",
                        result.details,
                        result.first_broken_seq,
                        result.total_checked,
                        self._runs_total,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Defense-in-depth: verify() может упасть (БД недоступна,
                # таблица не существует в dev_light) — loop продолжает жить.
                _logger.warning(
                    "audit HMAC-chain verify iteration failed: %s (run #%d)",
                    exc,
                    self._runs_total + 1,
                )
            await asyncio.sleep(self._interval_seconds)


#: Singleton — используется в lifecycle-хуках startup/shutdown.
default_scheduler: AuditVerifyScheduler | None = None


async def start_audit_verify(
    *, store: ImmutableAuditStore, interval_hours: float = 24.0
) -> None:
    """Запустить default audit verify scheduler (idempotent).

    Args:
        store: :class:`ImmutableAuditStore` (поверх Postgres session_factory).
        interval_hours: период verify (default 24h).

    """
    global default_scheduler
    if default_scheduler is not None and default_scheduler.is_running:
        # Already running — ничего не делаем (idempotent).
        return
    default_scheduler = AuditVerifyScheduler(store=store, interval_hours=interval_hours)
    await default_scheduler.start()


async def stop_audit_verify() -> None:
    """Остановить default audit verify scheduler (idempotent).

    NB: основной механизм graceful shutdown — ``TaskRegistry.shutdown_all()``
    в ``shutdown.py``, который отменяет все background-задачи. Эта функция
    обеспечивает явный graceful stop (дренаж текущей итерации).
    """
    global default_scheduler
    if default_scheduler is not None and default_scheduler.is_running:
        await default_scheduler.stop()


async def try_start_default(
    *, session_factory: Callable[[], Any], interval_hours: float = 24.0
) -> bool:
    """Запустить audit verify scheduler из startup-хука (best-effort).

    Действия:
        1. Проверить :data:`feature_flags.audit_hmac_verify_enabled` — если
           ``False``, вернуть ``False`` без side-effects (opt-in).
        2. Создать :class:`ImmutableAuditStore` через переданный
           ``session_factory`` (lazy import — избегаем circular-зависимости
           с database/db).
        3. Дёрнуть :func:`start_audit_verify` (idempotent).

    Все исключения логируются и глушатся: best-effort семантика
    совпадает с остальными startup-хуками (``startup.py`` всегда
    log+continue на optional subsystem). Возвращает ``True`` если
    scheduler реально запущен, ``False`` — если flag off или ошибка.

    Args:
        session_factory: async-callable → ``AsyncSession`` (обычно
            ``infrastructure.database.database.get_db_session``).
        interval_hours: период verify-итерации (default 24h).

    Returns:
        ``True`` если scheduler успешно запущен, ``False`` иначе.
    """
    try:
        from src.backend.core.config.features import feature_flags
        from src.backend.infrastructure.observability.immutable_audit import (
            ImmutableAuditStore,
        )

        if not getattr(feature_flags, "audit_hmac_verify_enabled", False):
            _logger.debug(
                "audit_hmac_verify_enabled=False, skip audit verify scheduler"
            )
            return False

        store = ImmutableAuditStore(session_factory=session_factory)
    except Exception as exc:
        # B-series: опциональная подсистема — log+continue.
        _logger.warning("audit verify scheduler bootstrap skipped: %s", exc)
        return False

    try:
        await start_audit_verify(store=store, interval_hours=interval_hours)
        return True
    except Exception as exc:
        _logger.warning("audit verify scheduler start failed: %s", exc)
        return False
