"""`LiteTemporalBackend` — in-process Temporal для dev_light/тестов (К3).

План V16.1 §4 Sprint 4: dev_light не должен требовать запущенного
Temporal-кластера. ``WorkflowEnvironment.start_local()`` (testing API
из ``temporalio``) поднимает Temporal in-process, использует SQLite
для persistence и предоставляет полноценный workflow API — поведение
**идентично** реальному кластеру.

Архитектура:
    * Наследует :class:`TemporalWorkflowBackend` — переиспользует все
      метод-реализации (``start_workflow`` / ``signal`` / ``query`` /
      ``cancel`` / ``await_completion`` / ``replay``).
    * :meth:`connect` запускает ``WorkflowEnvironment.start_local()``
      и берёт его ``client``.
    * :meth:`shutdown` (новый метод) — останавливает env и cleanup
      sqlite-файлов. Вызывается lifespan-hook'ом при shutdown
      приложения.

Использование (lifespan)::

    backend = await LiteTemporalBackend.connect()
    try:
        ...  # use as TemporalWorkflowBackend
    finally:
        await backend.shutdown()
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
    """In-process Temporal backend для dev_light (К3).

    Требует тех же extras что и :class:`TemporalWorkflowBackend`
    (``uv sync --extra workflow``); отличается только способом
    подключения — поднимает локальный сервер вместо connect к
    внешнему target'у.
    """

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
        """Возвращает поднятый ``WorkflowEnvironment``.

        Используется для регистрации Worker'а с in-process клиентом
        и в тестах для time-skipping.
        """
        return self._env

    @classmethod
    async def connect(  # type: ignore[override]
        cls,
        *,
        target: str = "<lite-temporal>",
        namespace: str = "default",
        default_task_queue: str = "default",
        api_key: str | None = None,
    ) -> "LiteTemporalBackend":
        """Поднять in-process Temporal env и вернуть backend.

        Параметры ``target`` / ``api_key`` игнорируются (in-process).
        Сохраняем сигнатуру родителя для уживаемости с factory.
        """
        try:
            from temporalio.testing import WorkflowEnvironment
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "temporalio SDK not installed. Install via `uv sync --extra workflow`."
            ) from exc
        del target, api_key  # unused — in-process

        env = await WorkflowEnvironment.start_local(
            namespace=namespace, data_converter=build_temporal_data_converter()
        )
        _logger.info(
            "LiteTemporalBackend started (in-process, namespace=%s)", namespace
        )
        return cls(client=env.client, env=env, default_task_queue=default_task_queue)

    async def shutdown(self) -> None:
        """Остановить in-process Temporal env и освободить ресурсы.

        Идемпотентен: повторный вызов — no-op. Вызывается lifespan-
        hook'ом приложения при shutdown.
        """
        env = self._env
        if env is None:
            return
        try:
            await env.shutdown()
        except Exception as exc:  # noqa: BLE001 — best-effort shutdown
            _logger.warning("LiteTemporalBackend env shutdown failed: %s", exc)
        finally:
            self._env = None  # type: ignore[assignment]
            _logger.info("LiteTemporalBackend shut down")
