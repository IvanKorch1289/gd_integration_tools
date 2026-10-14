"""Typed exceptions для LangGraph checkpoint contract (P0 fix 2026-10-14).

После удаления `langgraph_postgres_saver.py` (см. audit-stabilization
Proposal 3, commit 00cba5a71) feature-flag `langgraph_postgres_checkpoint`
оставался default=True, и `build_and_run_agent(..., durable=True)`
создавал agent с `checkpointer=None` silently. Это inversion semantics:
`durable=True` был слабее `durable=False`.

См. PROPOSALS_2026-10-14.md (P0 «логическая несогласованность
LangGraph»), Цель «Согласованность контрактов после удаления saver».

Этот файл — typed exception, которая поднимается когда durable=True
вызывается, но configured saver не доступен. Failure-loud: caller
получает типизированную ошибку, не silent checkpointer=None.
"""

from __future__ import annotations

from typing import Any


class CheckpointBackendUnavailable(Exception):
    """Typed exception: durable=True без configured checkpoint backend.

    Поднимается из :func:`build_and_run_agent <services.ai.ai_graph.build_and_run_agent>`
    когда `durable=True`, но checkpoint backend (например,
    AsyncPostgresSaver) не сконфигурирован. Это явный failure mode —
    не silent degradation.

    Mapping в HTTP:
    - REST action dispatcher: 503 Service Unavailable (не 200 с degraded
      ответом)
    - GraphQL: error extension code "CHECKPOINT_BACKEND_UNAVAILABLE"
    - agent supervisor: log + retry (с явным error) до reject

    Attributes:
        backend: Имя недоступного backend (например, "langgraph_postgres").
        thread_id: Запрошенный thread_id (если был указан).
        context: Дополнительный контекст для логирования.
    """

    def __init__(
        self,
        *,
        backend: str,
        thread_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.backend = backend
        self.thread_id = thread_id
        self.context = context or {}
        msg = f"Checkpoint backend {backend!r} недоступен"
        if thread_id:
            msg += f" (thread_id={thread_id!r})"
        super().__init__(msg)


__all__ = ("CheckpointBackendUnavailable",)
