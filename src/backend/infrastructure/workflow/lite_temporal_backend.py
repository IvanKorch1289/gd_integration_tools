"""`LiteTemporalBackend` — in-process Temporal для dev_light/тестов.

Поднимает ``WorkflowEnvironment.start_local()`` (SQLite persistence) и
переиспользует методы :class:`TemporalWorkflowBackend`. Поведение
идентично реальному кластеру.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.infrastructure.workflow.temporal_backend import (
    TemporalWorkflowBackend,
    build_temporal_data_converter,
)

if TYPE_CHECKING:  # pragma: no cover
    from temporalio.testing import WorkflowEnvironment

__all__ = ("LiteTemporalBackend",)
_logger = logging.getLogger("workflow.lite_temporal_backend")


class LiteTemporalBackend(TemporalWorkflowBackend):
    """In-process Temporal backend для dev_light (`uv sync --extra workflow`)."""

    def __init__(
        self,
        *,
        client: Any,
        env: WorkflowEnvironment,
        default_task_queue: str = "default",
    ) -> None:
        super().__init__(client=client, default_task_queue=default_task_queue)
        self._env = env

    @property
    def env(self) -> WorkflowEnvironment:
        """Поднятый ``WorkflowEnvironment`` (для Worker и time-skipping)."""
        return self._env

    @classmethod
    async def connect(  
        cls,
        *,
        target: str = "<lite-temporal>",
        namespace: str = "default",
        default_task_queue: str = "default",
        api_key: str | None = None,
    ) -> "LiteTemporalBackend":
        """Поднять in-process env; ``target`` / ``api_key`` игнорируются."""
        try:
            from temporalio.testing import WorkflowEnvironment
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "temporalio SDK not installed. Install via `uv sync --extra workflow`."
            ) from exc
        del target, api_key
        env = await WorkflowEnvironment.start_local(
            namespace=namespace, data_converter=build_temporal_data_converter()
        )
        _logger.info("LiteTemporalBackend started (namespace=%s)", namespace)
        return cls(client=env.client, env=env, default_task_queue=default_task_queue)

    async def shutdown(self) -> None:
        """Идемпотентный shutdown env (lifespan-hook)."""
        if self._env is None:
            return
        try:
            await self._env.shutdown()
        except Exception as exc:  # noqa: BLE001 — best-effort shutdown
            _logger.warning("LiteTemporalBackend env shutdown failed: %s", exc)
        finally:
            self._env = None  
            _logger.info("LiteTemporalBackend shut down")
