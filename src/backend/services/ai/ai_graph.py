"""LangGraph агентский граф (LiteLLMGateway-backed).

Определяет граф ReAct-агента, который использует зарегистрированные actions
как инструменты (LangChain tools) и :class:`LiteLLMGateway` как
единый шлюз LLM-провайдеров.

В отличие от прежней реализации (hardcoded ``ChatOpenAI``), сейчас:

* Модель/fallback-chain/timeout берутся из :mod:`core.config.ai_2026`
  через :class:`LiteLLMGateway` — единый шлюз LLM.
* Cost-tracking автоматически подключается через ``litellm.success_callback``
  (см. :mod:`services.ai.gateway.callbacks`).
* Поддерживается multi-provider (OpenAI, Anthropic, локальные модели) без
  изменения кода — конфигурация в env / settings.

Lazy-import:
    Тяжёлые AI-зависимости (``langgraph``, ``langchain_litellm``,
    ``langchain_core``) импортируются внутри функций — это позволяет
    модулю быть импортированным в окружениях без extra ``[ai-2026]``.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.request_context import RequestContext

__all__ = ("build_and_run_agent", "build_chat_model")

logger = get_logger(__name__)


def _make_action_tool(action_name: str) -> Any:
    """Создаёт async-only LangChain-tool из зарегистрированного action.

    Block 2.2 (gap-ai-2.2): инструмент возвращается БЕЗ sync-обёртки
    (``_sync_run`` удалён). Предыдущая реализация делала ``asyncio.run``
    внутри ``ThreadPoolExecutor`` при работающем event loop, что под
    нагрузкой давало ``RuntimeError: asyncio.run() cannot be called from
    a running event loop`` (вложенный loop в worker-потоке создавал
    deadlock на shared connection pools / DB sessions).

    Текущая реализация:
        * Только ``coroutine=_run_action`` в ``StructuredTool.from_function``;
        * LangChain автоматически генерирует sync-wrapper через
          ``asyncio.run_coroutine_threadsafe`` либо отвергает sync-вызов
          с понятной ошибкой (LangGraph всегда использует async-path).

    Args:
        action_name: Имя action в :class:`ActionHandlerRegistry`.

    Returns:
        :class:`StructuredTool` обёртка, диспетчеризующая в
        ``action_handler_registry.dispatch``.
    """
    from langchain_core.tools import StructuredTool

    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.schemas.invocation import ActionCommandSchema

    async def _run_action(**kwargs: Any) -> str:
        command = ActionCommandSchema(
            action=action_name, payload=kwargs, meta={"source": "ai_agent"}
        )
        result = await action_handler_registry.dispatch(command)
        if hasattr(result, "model_dump"):
            return str(result.model_dump(mode="json"))
        return str(result)

    return StructuredTool.from_function(
        coroutine=_run_action,
        name=action_name.replace(".", "_"),
        description=f"Выполняет action '{action_name}' через ActionHandlerRegistry",
    )


def build_chat_model(
    *,
    gateway: Any | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    **extra_kwargs: Any,
) -> Any:
    """Создаёт LangChain-compatible chat-model поверх :class:`LiteLLMGateway`.

    Использует ``ChatLiteLLM`` адаптер (либо из ``langchain_litellm``, либо
    из ``langchain_community``), конфигурируя его параметрами из
    :class:`LiteLLMGateway` (``default_model``, ``fallback_models``,
    ``timeout``, ``num_retries``).

    Args:
        gateway: Опц. :class:`LiteLLMGateway`. При ``None`` используется
            singleton ``get_litellm_gateway()``.
        model: Явный model identifier. При ``None`` берётся из gateway.
        temperature: Параметр sampling-температуры LLM.
        **extra_kwargs: Дополнительные kwargs, прокидываемые в ChatLiteLLM
            (например, ``max_tokens``, ``top_p``).

    Returns:
        LangChain ``BaseChatModel`` совместимый объект.

    Raises:
        ImportError: Если ни ``langchain_litellm``, ни
            ``langchain_community`` не установлены.
    """
    from src.backend.services.ai.gateway import get_litellm_gateway

    gw = gateway if gateway is not None else get_litellm_gateway()
    resolved_model = model or gw._default_model
    fallbacks = list(gw._fallbacks)
    timeout = gw._timeout
    num_retries = gw._num_retries

    chat_kwargs: dict[str, Any] = {
        "model": resolved_model,
        "temperature": temperature,
        "request_timeout": timeout,
        "num_retries": num_retries,
        **extra_kwargs,
    }
    if fallbacks:
        chat_kwargs["fallbacks"] = fallbacks

    try:
        from langchain_litellm import ChatLiteLLM  # type: ignore[import-not-found]
    except ImportError:
        try:
            from langchain_community.chat_models import ChatLiteLLM
        except ImportError as exc:
            raise ImportError(
                "ChatLiteLLM недоступен: установите 'langchain-litellm' "
                "или 'langchain-community' (extra '[ai-2026]')."
            ) from exc

    return ChatLiteLLM(**chat_kwargs)


async def build_and_run_agent(
    prompt: str,
    tool_actions: list[str],
    *,
    gateway: Any | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    durable: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Строит и запускает LangGraph-агента через :class:`AIGateway`.

    S85 W2 (V2 P0 #1): было — обход через LiteLLMGateway напрямую.
    Теперь — enforcement check в AIGateway перед LiteLLM call.
    Audit/policy/capability теперь ВСЕГДА active для LangGraph-агентов.

    Args:
        prompt: Задача для агента.
        tool_actions: Список имён actions, доступных как tools.
        gateway: Опц. :class:`LiteLLMGateway` (для DI/тестов). Если
            ``None`` — singleton.
        model: Явный model identifier. При ``None`` берётся из gateway.
        temperature: Sampling-температура LLM.
        durable: При True — подключает LangGraph PostgresCheckpointer
            (требует ``feature_flags.langgraph_postgres_checkpoint=True``).
            При недоступности — fallback на in-memory checkpointing.
        session_id: Опц. ID сессии; используется как LangGraph ``thread_id``.
            При ``None`` — берётся ``correlation_id`` из текущего
            :class:`RequestContext` либо генерируется UUID4.

    Returns:
        Результат работы агента: словарь с ``prompt``, ``tools_used``,
        ``response``, ``message_count`` либо ``error``.
    """
    try:
        from langgraph.prebuilt import create_react_agent

        # S85 W2 (V2 P0 #1): enforcement check через AIGateway
        # перед LiteLLM call. Если enforcement не пройден —
        # возврат с error без silent pass-through.
        from src.backend.core.ai.gateway import AIGateway
        from src.backend.core.config.features import feature_flags

        # S85 W2: pre-flight enforcement check.
        # AIGateway._enforced_invoke внутри вызывает _resolve_policy и
        # _check_capability. Здесь мы делаем минимальный pre-flight —
        # если ai_gateway_enforce=False, бросаем сразу (silent pass-through
        # запрещён, см. S85 W1).
        if not feature_flags.ai_gateway_enforce:
            from src.backend.core.ai.errors import AIGatewayEnforcementRequiredError

            raise AIGatewayEnforcementRequiredError(
                "ai_graph.build_and_run_agent requires ai_gateway_enforce=True "
                "(S85 W2: bypass via LiteLLMGateway is no longer supported)"
            )
        ai_gateway = AIGateway()  # enforce instance для downstream hooks  # noqa: F841

        tools = [_make_action_tool(action) for action in tool_actions]
        llm = build_chat_model(
            gateway=gateway, model=model, temperature=temperature
        )

        checkpointer: Any | None = None
        if durable:
            from src.backend.services.ai.agents.langgraph_postgres_saver import (
                get_langgraph_postgres_saver,
            )

            saver = await get_langgraph_postgres_saver()
            if saver is not None:
                checkpointer = saver
                logger.debug("LangGraph Checkpointer: using PostgresSaver")
            else:
                logger.debug(
                    "LangGraph Checkpointer: PostgresSaver unavailable, "
                    "using MemorySaver"
                )
                from langgraph.checkpoint.memory import MemorySaver

                checkpointer = MemorySaver()

        agent = create_react_agent(
            llm, tools, checkpointer=checkpointer, max_iterations=10
        )

        thread_id = session_id or ""
        if not thread_id:
            ctx = RequestContext.current()
            thread_id = ctx.correlation_id if ctx is not None else uuid.uuid4().hex

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"configurable": {"thread_id": thread_id}},
        )

        messages = result.get("messages", [])
        final_content = messages[-1].content if messages else ""

        return {
            "prompt": prompt,
            "tools_used": tool_actions,
            "response": final_content,
            "message_count": len(messages),
        }
    except ImportError as exc:
        logger.warning("LangGraph/LiteLLM не доступен: %s", exc)
        return {"error": f"Зависимости не установлены: {exc}"}
    except Exception as exc:
        logger.error("Agent execution error: %s", exc, exc_info=True)
        return {"error": str(exc)}
