"""AI/Workflow RouteBuilder contracts (W9 P2-13 split).

AI/ML + Temporal workflow + agent DSL семейство — все операции AI/agent/
workflow: LLM/RAG/inference/structured_output, Temporal orchestration
(invoke/cancel/sub/cron), agent graph/memory/skills.

ADR-0320: вынесено из ``_protocols.py`` (1094 LOC god-module) в отдельный
sub-module ``_ai.py`` как часть W9 P2-13 (god-object decomposition).
"""

from __future__ import annotations

from typing import Any
from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable


@_runtime_checkable
class _RouteAIOpsProtocol(_Protocol):
    """Contract: AI/ML операции (LLM/RAG/inference/structured)."""

    def llm_structured(
        self,
        *,
        model: str,
        output_schema: Any,
        prompt: str,
        retry: int = 3,
        temperature: float = 0.0,
        cost_budget_usd: float | None = None,
        to: str = "body.llm_result",
        name: str | None = None,
    ) -> Any: ...
    def ml_predict(
        self,
        model: str,
        *,
        input_field: str = "body.features",
        output_property: str = "ml_prediction",
        model_type: str | None = None,
        name: str | None = None,
    ) -> Any: ...
    def call_llm(
        self, *, prompt: str, model: str | None = None, to: str = "body.llm_result"
    ) -> Any: ...
    def parse_llm_output(self, schema: Any | None = None) -> Any: ...
    def token_budget(self, max_tokens: int = 4096) -> Any: ...
    def llm_fallback(self, *models: str) -> Any: ...
    def rag_search(
        self, query: str, *, top_k: int = 5, to: str = "body.rag_hits"
    ) -> Any: ...
    def rag_query(
        self, query: str, *, top_k: int = 5, to: str = "body.rag_result"
    ) -> Any: ...


@_runtime_checkable
class _RouteWorkflowOpsProtocol(_Protocol):
    """Contract: Temporal workflow orchestration (invoke/cancel/sub/schedule/audit)."""

    def invoke_workflow(
        self,
        name: str,
        *,
        mode: str = "async-api",
        args: dict[str, Any] | None = None,
        namespace: str = "default",
        task_queue: str = "default",
        result_property: str = "workflow_result",
        invocation_id_property: str = "invocation_id",
        reply_timeout_seconds: float = 60.0,
        version: str | None = None,
    ) -> Any: ...
    def cancel_workflow(
        self,
        workflow_id: str,
        *,
        reason: str = "",
        namespace: str = "default",
        result_property: str = "cancel_result",
    ) -> Any: ...
    def sub_workflow(
        self,
        name: str,
        args: dict[str, Any],
        *,
        namespace: str = "default",
        task_queue: str = "default",
        sub_workflow_id_property: str = "sub_workflow_id",
        result_property: str = "sub_workflow_result",
        parent_workflow_id_property: str = "workflow_id",
        parent_correlation_id_property: str = "correlation_id",
    ) -> Any: ...
    def cron_schedule(
        self,
        name: str,
        *,
        cron_expr: str,
        workflow_name: str,
        workflow_args: dict[str, Any] | None = None,
        namespace: str = "default",
        task_queue: str = "default",
        result_property: str = "schedule_handle",
        timezone: str = "UTC",
    ) -> Any: ...
    def audit(
        self,
        *,
        action: str | None = None,
        action_from: str | None = None,
        actor: str = "system",
        actor_from: str | None = None,
        resource_from: str | None = None,
        outcome: str = "success",
        outcome_from: str | None = None,
        metadata_from: str | None = None,
        tenant_id_from: str | None = None,
        correlation_id_from: str | None = None,
        result_property: str = "audit_event_hash",
    ) -> Any: ...


@_runtime_checkable
class _RouteAgentProtocol(_Protocol):
    """Contract: agent DSL (graph/memory/skills/branch/loop/parallel)."""

    def agent_graph(self, *, nodes: list[Any], edges: list[Any], entry: str) -> Any: ...
    def skill_invoke(
        self, skill: str, *, args: dict[str, Any] | None = None
    ) -> Any: ...
    def ai_memory_recall(
        self, query: str, *, top_k: int = 5, to: str = "body.memory_recall"
    ) -> Any: ...
    def ai_memory_store(
        self, *, key: str | None = None, value: Any | None = None
    ) -> Any: ...
    def ai_invoke(
        self,
        skill: str,
        *,
        args: dict[str, Any] | None = None,
        result_property: str = "ai_result",
    ) -> Any: ...
    def agent_branch(
        self, when: Any, _then_procs: list[Any], _else_procs: list[Any]
    ) -> Any: ...
    def agent_loop(
        self,
        processors: list[Any],
        *,
        until: Any | None = None,
        max_iterations: int = 10,
    ) -> Any: ...
    def agent_parallel(
        self, branches: dict[str, list[Any]], *, strategy: str = "all"
    ) -> Any: ...
