from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.interfaces.ai_clients import AISanitizerProtocol

from src.backend.core.logging import get_logger

logger = get_logger(__name__)


class AgentOrchestrationMixin:
    """agent orchestration (chat, run_agent, _record_feedback) для AIAgentService. S54 W2 extraction."""

    # State attrs + cross-method hints (S54 W2: class-level annotations for mypy MRO)
    _sanitizer: "AISanitizerProtocol"
    _ai_cfg: Any
    _providers: dict[str, Any]
    _open_webui: Any
    _waf_headers: Any
    _waf_url: Any
    _agent_metrics_service: Any
    _agent_tracer: Any
    _agent_redis: Any
    _get_http_client: Any
    _extract_agent_response: Any
    _call_perplexity: Any  # http_providers
    _policy_gate: Any  # policy
    _maybe_augment_with_rag: Any  # rag
    _resolve_rag_service: Any  # rag
    _resolve_authz_gateway: Any  # policy
    _get_metrics_service: Any  # core (in http_providers)
    __slots__ = ()

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "default",
        provider: str | None = None,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        rag_namespace: str | None = None,
        rag_top_k: int | None = None,
        rag_system_prompt: str = "",
        tenant_id: str | None = None,
        route_id: str | None = None,
    ) -> dict[str, Any]:
        """Чат с LLM через мульти-провайдерную архитектуру.

        Данные маскируются перед отправкой, восстанавливаются после.
        При недоступности провайдера — fallback на следующий.
        Каждый успешный ответ автоматически сохраняется в
        ``AIFeedbackService`` для последующей разметки оператором.

        Если задан ``rag_namespace`` и ``rag_settings.enabled=True``,
        последний user-message предварительно обогащается контекстом
        из векторного хранилища через ``RAGService.augment_prompt``.
        Ошибки RAG не прерывают основной flow (best-effort).

        Args:
            messages: [{role, content}].
            model: Идентификатор модели.
            provider: Конкретный провайдер (или fallback-chain).
            session_id: Идентификатор сессии (для feedback).
            metadata: Дополнительные поля в feedback (tenant_id и т.д.).
            rag_namespace: Namespace в RAG (например, "notebooks").
                None — обогащение отключено для этого вызова.
            rag_top_k: Кол-во чанков при retrieval. None — берёт
                ``rag_settings.top_k``.
            rag_system_prompt: System-prompt, который дополнит RAG-контекст.

        Returns:
            Ответ LLM с восстановленными PII. Дополнительно в ответ
            добавляется ``feedback_id`` — идентификатор записи
            в ``AIFeedbackService`` (для кнопок ✅/❌ на стороне UI).
        """
        # Block 1.5 (gap-ai-1.5, ADR-0072): AuthorizationGateway policy gate
        # выполняется ПЕРВЫМ — до RAG retrieval и sanitize. Fail-closed: любая
        # ошибка резолва / authorize → deny + audit-event без LLM-вызова.
        gate_denial = await self._policy_gate(
            model=model, tenant_id=tenant_id, route_id=route_id, metadata=metadata
        )
        if gate_denial is not None:
            return gate_denial

        rag_used, messages = await self._maybe_augment_with_rag(
            messages=messages,
            namespace=rag_namespace,
            top_k=rag_top_k,
            system_prompt=rag_system_prompt,
        )

        sanitized_msgs, mapping = self._sanitizer.sanitize_messages(messages)

        chain = [provider] if provider else self._ai_cfg.fallback_chain
        last_error: str | None = None
        metrics = self._get_metrics_service()

        for prov_name in chain:
            call_fn = self._providers.get(prov_name)
            if call_fn is None:
                continue

            import time as _time

            started = _time.perf_counter()
            try:
                result = await call_fn(sanitized_msgs, model=model)

                content = ""
                usage: dict[str, Any] = {}
                if isinstance(result, dict):
                    choices = result.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                    elif "generated_text" in result:
                        content = result["generated_text"]
                    elif isinstance(result.get("data"), str):
                        content = result["data"]
                    usage = result.get("usage") or {}

                restored = self._sanitizer.restore_text(content, mapping)

                if metrics is not None:
                    metrics.record_execution(
                        agent_id="chat",
                        provider=prov_name,
                        duration_seconds=_time.perf_counter() - started,
                        status="success",
                    )
                    metrics.record_tokens(
                        provider=prov_name,
                        model=model,
                        input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                        output_tokens=int(usage.get("completion_tokens", 0) or 0),
                    )
                    cost = float(usage.get("cost_usd", 0.0) or 0.0)
                    if cost:
                        metrics.record_cost(
                            provider=prov_name, model=model, cost_usd=cost
                        )

                feedback_meta: dict[str, Any] = {
                    **(metadata or {}),
                    "model": model,
                    "provider": prov_name,
                }
                if rag_used:
                    feedback_meta["rag_used"] = True
                    feedback_meta["rag_namespace"] = rag_namespace
                feedback_id = await self._record_feedback(
                    messages=messages,
                    response=restored,
                    agent_id=f"chat:{prov_name}",
                    session_id=session_id,
                    metadata=feedback_meta,
                )

                response: dict[str, Any] = {
                    "success": True,
                    "content": restored,
                    "provider": prov_name,
                    "model": model,
                    "feedback_id": feedback_id,
                }
                if rag_used:
                    response["rag_used"] = True
                    response["rag_namespace"] = rag_namespace
                return response
            except Exception as exc:
                last_error = f"{prov_name}: {exc}"
                logger.warning("AI provider '%s' failed: %s", prov_name, exc)
                if metrics is not None:
                    metrics.record_execution(
                        agent_id="chat",
                        provider=prov_name,
                        duration_seconds=_time.perf_counter() - started,
                        status="error",
                    )

        return {"success": False, "error": f"All providers failed. Last: {last_error}"}

    async def run_agent(
        self,
        prompt: str,
        tools: list[str] | None = None,
        *,
        agent_id: str = "default",
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        durable: bool = False,
    ) -> dict[str, Any]:
        """Запуск AI-агента с маскировкой PII.

        После успешного ответа автоматически сохраняет результат
        в ``AIFeedbackService`` для последующей разметки оператором.

        Args:
            prompt: Текст запроса к агенту.
            tools: Опц. список имён action'ов, доступных агенту.
            agent_id: Идентификатор агента (для feedback).
            session_id: Идентификатор сессии (для LangGraph Checkpointer
                persistence). При ``durable=True`` требует настроенный
                ``feature_flags.langgraph_postgres_checkpoint``.
            metadata: Дополнительные поля в feedback.
            durable: При True — включает LangGraph PostgresCheckpointer
                для stateful-сессий (resume после interruption).
        """
        sanitized = self._sanitizer.sanitize_text(prompt)

        try:
            from src.backend.services.ai.ai_graph import build_and_run_agent

            result = await build_and_run_agent(
                prompt=sanitized.sanitized, tool_actions=tools or [], durable=durable
            )

            if isinstance(result, str):
                result = sanitized.restore(result)

            feedback_id = await self._record_feedback(
                messages=[{"role": "user", "content": prompt}],
                response=self._extract_agent_response(result),
                agent_id=agent_id,
                session_id=session_id,
                metadata={**(metadata or {}), "tools": tools or []},
            )
            return {"success": True, "data": result, "feedback_id": feedback_id}
        except ImportError:
            return {"success": False, "error": "langgraph не установлен."}
        except Exception as exc:
            logger.error("Agent run error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _record_feedback(
        self,
        *,
        messages: list[dict[str, str]],
        response: str,
        agent_id: str,
        session_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> str | None:
        """Сохраняет ответ агента в ``AIFeedbackService``.

        Ошибки записи не распространяются наверх: сбой feedback
        не должен ломать основной AI-поток. При отсутствии сервиса
        (старт без ``app.state``) возвращает ``None``.

        Args:
            messages: История сообщений (извлекается последний user).
            response: Восстановленный текст ответа LLM/агента.
            agent_id: Идентификатор агента.
            session_id: Идентификатор сессии.
            metadata: Поля метаданных (провайдер, модель и т.д.).

        Returns:
            ``feedback_id`` записи либо ``None`` при ошибке.
        """
        try:
            from src.backend.services.ai.feedback import get_ai_feedback_service

            service = get_ai_feedback_service()
            query = next(
                (
                    m.get("content", "")
                    for m in reversed(messages)
                    if m.get("role") == "user"
                ),
                "",
            )
            return await service.save_response(
                query=query or "",
                response=response or "",
                agent_id=agent_id,
                session_id=session_id,
                metadata=metadata or {},
            )
        except Exception as exc:
            logger.warning("ai_feedback_save_failed: %s", exc)
            return None
