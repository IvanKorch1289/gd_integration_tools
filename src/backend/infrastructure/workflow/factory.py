"""Profile-based factory для `WorkflowBackend` (Wave D.2 / ADR-045).

Settings.workflow_backend = ``temporal | lite_temporal | pg_runner | fake | auto``:

* ``auto`` — выбирается по profile: dev_light → lite_temporal;
  dev/staging/prod → temporal (если установлен SDK), иначе fallback
  pg_runner с warning'ом **только в dev-профилях**. Fallback —
  **degraded-режим**: он теряет replay, детерминизм и typed-query
  (ADR-0395). Явный ``kind="temporal"`` никогда не деградирует — ошибка
  подключения пробрасывается наружу.
* ``temporal`` — :class:`TemporalWorkflowBackend` (требует extras
  ``workflow``: ``uv sync --extra workflow``).
* ``lite_temporal`` — :class:`LiteTemporalBackend` (in-process Temporal
  через ``WorkflowEnvironment.start_local()`` + SQLite; требует extras
  ``workflow``). Идентичная real-кластеру семантика для dev_light/тестов.
* ``pg_runner`` — :class:`PgRunnerWorkflowBackend` (без extras).
* ``fake`` — :class:`FakeWorkflowBackend` (только для тестов).

ADR-0399 (исполнение обещания ADR-0395): **downgrade Temporal → pg_runner
запрещён в staging/prod**. В этих профилях падение коннекта к Temporal —
ошибка с понятным сообщением, а не тихая деградация. Профиль берётся из
аргумента ``profile``, а при его отсутствии — из ``APP_PROFILE``
(см. :func:`src.backend.core.config.profile.get_active_profile`), поэтому
вызовы ``kind="auto"`` без профиля (например ``manage.py workflow cancel``)
тоже защищены.

Factory сознательно использует lazy-import конкретных impl'ов,
чтобы import core-модулей не тянул heavy SDK.
"""

from __future__ import annotations

from typing import Final, Literal

from src.backend.core.logging import get_logger
from src.backend.core.workflow.backend import WorkflowBackend
from src.backend.core.workflow.fake_backend import FakeWorkflowBackend

__all__ = ("BackendKind", "create_workflow_backend")


_logger = get_logger("workflow.factory")


BackendKind = Literal["temporal", "lite_temporal", "pg_runner", "fake", "auto"]

#: Гарантии, которые теряются при downgrade'е Temporal → pg_runner.
#: ADR-0395: downgrade — degraded-режим, а не равноценная замена.
_LOST_GUARANTEES: tuple[str, ...] = (
    "replay (историю выполнения нельзя переиграть в CI versioning-gate)",
    "determinism (pg-runner не даёт sandbox-детерминированных команд)",
    "typed-query (query_workflow не поддерживается pg-runner'ом)",
)

#: Профили, в которых автоматический downgrade Temporal → pg_runner запрещён.
#: ADR-0395/ADR-0399: staging/prod теряют гарантии исполнения — оператор
#: обязан поднять Temporal-кластер, деградация допустима только в dev.
_STRICT_PROFILES: Final[frozenset[str]] = frozenset({"staging", "prod"})


def _resolve_profile(profile: str | None) -> str:
    """Определить эффективный профиль запуска.

    Args:
        profile: Явно переданный профиль (``None`` → берётся ``APP_PROFILE``).

    Returns:
        Имя профиля (``dev_light`` / ``dev`` / ``staging`` / ``prod``).

    """
    if profile:
        return profile.strip().lower()
    from src.backend.core.config.profile import get_active_profile

    return str(get_active_profile())


async def create_workflow_backend(
    *,
    kind: BackendKind = "auto",
    profile: str | None = None,
    temporal_target: str = "localhost:7233",
    temporal_namespace: str = "default",
    temporal_task_queue: str = "default",
) -> WorkflowBackend:
    """Создать backend по конфигу.

    :param kind: явный выбор. ``"auto"`` — по profile.
    :param profile: APP_PROFILE (``dev_light`` / ``dev`` / ``staging`` /
        ``prod``). Используется при ``kind="auto"`` и для проверки
        допустимости downgrade'а; при ``None`` берётся из ``APP_PROFILE``.
    :param temporal_target: адрес Temporal-сервера (для ``temporal``).
    :param temporal_namespace: Temporal namespace.
    :param temporal_task_queue: default task_queue для start_workflow.

    :raises RuntimeError: в профилях ``staging``/``prod`` автоматический
        downgrade Temporal → pg_runner запрещён (ADR-0395/ADR-0399).
    """
    active_profile = _resolve_profile(profile)
    resolved = kind
    if resolved == "auto":
        if active_profile == "dev_light":
            # Sprint 7 P0-3: dev_light → lite_temporal (was pg_runner DEPRECATED since Sprint 217).
            # CLAUDE.md V22 уже говорит "Lite в dev_light" — это была фактическая фиксация
            # задокументированной семантики. lite_temporal требует extras "workflow" (temporalio SDK);
            # при ImportError fallback to pg_runner ниже (см. lite_temporal branch).
            resolved = "lite_temporal"
        else:
            resolved = "temporal"

    if resolved == "fake":
        return FakeWorkflowBackend()

    if resolved == "pg_runner":
        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        return PgRunnerWorkflowBackend()

    if resolved == "lite_temporal":
        try:
            from src.backend.infrastructure.workflow.lite_temporal_backend import (
                LiteTemporalBackend,
            )
        except ImportError as exc:
            _logger.warning(
                "temporalio SDK unavailable (%s); falling back to pg_runner", exc
            )
            from src.backend.infrastructure.workflow.pg_runner_backend import (
                PgRunnerWorkflowBackend,
            )

            return PgRunnerWorkflowBackend()

        return await LiteTemporalBackend.connect(
            namespace=temporal_namespace, default_task_queue=temporal_task_queue
        )

    if resolved == "temporal":
        try:
            from src.backend.infrastructure.workflow.temporal_backend import (
                TemporalWorkflowBackend,
            )

            return await TemporalWorkflowBackend.connect(
                target=temporal_target,
                namespace=temporal_namespace,
                default_task_queue=temporal_task_queue,
            )
        except Exception as exc:
            # ADR-0395: ловим ЛЮБУЮ ошибку подключения (OSError,
            # ConnectionError, temporalio RPCError, TimeoutError, ...),
            # а не только RuntimeError. Раньше падение коннекта к
            # Temporal-кластеру (например, недоступный хост) не давало
            # fallback'а — приложение падало вместо деградации.
            if kind == "temporal":
                # Явный выбор оператора — downgrade недопустим: он тихо
                # меняет семантику исполнения (см. _LOST_GUARANTEES).
                _logger.error(
                    "Temporal connect failed (%s: %s) — explicit kind='temporal', "
                    "downgrade to pg_runner запрещён.",
                    type(exc).__name__,
                    exc,
                )
                raise
            if active_profile in _STRICT_PROFILES:
                # ADR-0395/ADR-0399: staging/prod — downgrade запрещён.
                # Тихой деградации здесь быть не должно: оператор обязан
                # поднять Temporal-кластер (или выбрать движок явно).
                _logger.error(
                    "Temporal connect failed (%s: %s) — профиль %s: downgrade "
                    "to pg_runner запрещён. ПОТЕРЯННЫЕ ГАРАНТИИ: %s",
                    type(exc).__name__,
                    exc,
                    active_profile,
                    "; ".join(_LOST_GUARANTEES),
                )
                raise RuntimeError(
                    f"Temporal connect failed ({type(exc).__name__}: {exc}) — "
                    f"downgrade Temporal → pg_runner запрещён в профиле "
                    f"{active_profile!r} (ADR-0395/ADR-0399). "
                    f"ПОТЕРЯННЫЕ ГАРАНТИИ: {'; '.join(_LOST_GUARANTEES)}"
                ) from exc
            _logger.warning(
                "Temporal connect failed (%s: %s) — degraded fallback to "
                "pg_runner. ПОТЕРЯННЫЕ ГАРАНТИИ: %s",
                type(exc).__name__,
                exc,
                "; ".join(_LOST_GUARANTEES),
            )
            from src.backend.infrastructure.workflow.pg_runner_backend import (
                PgRunnerWorkflowBackend,
            )

            return PgRunnerWorkflowBackend()

    raise ValueError(f"Unknown WorkflowBackend kind: {kind!r}")
