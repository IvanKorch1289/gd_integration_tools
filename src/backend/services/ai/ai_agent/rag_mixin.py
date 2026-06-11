from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.interfaces.ai_clients import AISanitizerProtocol

from src.backend.core.logging import get_logger

logger = get_logger(__name__)


class RagMixin:
    """RAG integration (_maybe_augment_with_rag, _resolve_rag_service) для AIAgentService. S54 W2 extraction."""

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
    _call_perplexity: Any
    _policy_gate: Any

    _get_metrics_service: Any

    _resolve_authz_gateway: Any
    __slots__ = ()

    async def _maybe_augment_with_rag(
        self,
        *,
        messages: list[dict[str, str]],
        namespace: str | None,
        top_k: int | None,
        system_prompt: str,
    ) -> tuple[bool, list[dict[str, str]]]:
        """Best-effort обогащение последнего user-сообщения RAG-контекстом.

        Возвращает ``(rag_used, messages)``. Если RAG отключён, namespace
        пуст или произошла ошибка — возвращает исходный список сообщений
        без модификации.

        Args:
            messages: Исходный список сообщений чата.
            namespace: Namespace в RAG. None — обогащение пропускается.
            top_k: Кол-во чанков; None — берёт ``rag_settings.top_k``.
            system_prompt: System-prompt, который RAGService включит
                в augmented-промпт.

        Returns:
            (use_flag, messages) — флаг включения RAG и потенциально
            модифицированный список сообщений.
        """
        if not namespace:
            return False, messages

        try:
            from src.backend.core.config.rag import rag_settings
        except Exception as exc:
            logger.warning("rag_settings недоступны: %s", exc)
            return False, messages

        if not rag_settings.enabled:
            return False, messages

        rag = self._resolve_rag_service()
        if rag is None:
            return False, messages

        last_user_idx = next(
            (
                i
                for i in range(len(messages) - 1, -1, -1)
                if messages[i].get("role") == "user"
            ),
            -1,
        )
        if last_user_idx < 0:
            return False, messages

        query = messages[last_user_idx].get("content", "")
        if not query:
            return False, messages

        try:
            augmented = await rag.augment_prompt(
                query=query,
                system_prompt=system_prompt,
                top_k=top_k or rag_settings.top_k,
                namespace=namespace,
            )
        except Exception as exc:
            logger.warning("rag_augment_failed namespace=%s: %s", namespace, exc)
            return False, messages

        new_messages = list(messages)
        new_messages[last_user_idx] = {**messages[last_user_idx], "content": augmented}
        return True, new_messages

    @staticmethod
    def _resolve_rag_service() -> Any:
        """Lazy-получение singleton RAGService с защитой от ошибок инициализации.

        Если зависимости RAG недоступны (qdrant, sentence-transformers и т.д.)
        либо vector store не запущен — возвращает None, не ломая основной flow.

        Returns:
            ``RAGService`` либо ``None``.
        """
        try:
            from src.backend.services.ai.rag_service import get_rag_service

            return get_rag_service()
        except Exception as exc:
            logger.warning("rag_service_resolve_failed: %s", exc)
            return None
