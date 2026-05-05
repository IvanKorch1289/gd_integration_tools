"""Profile-based factory для `WorkflowBackend` (Wave D.2 / ADR-045).

Settings.workflow_backend = ``temporal | pg_runner | fake | auto``:

* ``auto`` — выбирается по profile: dev_light → pg_runner; dev/staging/
  prod → temporal (если установлен SDK), иначе fallback pg_runner с
  warning'ом.
* ``temporal`` — :class:`TemporalWorkflowBackend` (требует extras
  ``workflow``: ``uv sync --extra workflow``).
* ``pg_runner`` — :class:`PgRunnerWorkflowBackend` (без extras).
* ``fake`` — :class:`FakeWorkflowBackend` (только для тестов).

Factory сознательно использует lazy-import конкретных impl'ов,
чтобы import core-модулей не тянул heavy SDK.
"""

from __future__ import annotations

import logging
from typing import Literal

from src.core.workflow.backend import WorkflowBackend
from src.core.workflow.fake_backend import FakeWorkflowBackend

__all__ = ("BackendKind", "create_workflow_backend")


_logger = logging.getLogger("workflow.factory")


BackendKind = Literal["temporal", "pg_runner", "fake", "auto"]


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
        ``prod``) — используется только при ``kind="auto"``.
    :param temporal_target: адрес Temporal-сервера (для ``temporal``).
    :param temporal_namespace: Temporal namespace.
    :param temporal_task_queue: default task_queue для start_workflow.
    """
    resolved = kind
    if resolved == "auto":
        if profile == "dev_light":
            resolved = "pg_runner"
        else:
            resolved = "temporal"

    if resolved == "fake":
        return FakeWorkflowBackend()

    if resolved == "pg_runner":
        from src.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        return PgRunnerWorkflowBackend()

    if resolved == "temporal":
        try:
            from src.infrastructure.workflow.temporal_backend import (
                TemporalWorkflowBackend,
            )

            return await TemporalWorkflowBackend.connect(
                target=temporal_target,
                namespace=temporal_namespace,
                default_task_queue=temporal_task_queue,
            )
        except RuntimeError as exc:
            _logger.warning(
                "Temporal SDK unavailable (%s); falling back to pg_runner", exc
            )
            from src.infrastructure.workflow.pg_runner_backend import (
                PgRunnerWorkflowBackend,
            )

            return PgRunnerWorkflowBackend()

    raise ValueError(f"Unknown WorkflowBackend kind: {kind!r}")
