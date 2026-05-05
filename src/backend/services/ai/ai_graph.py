"""LangGraph агентский граф.

Определяет граф агента, который может использовать
зарегистрированные actions как инструменты (tools).
"""

import logging
from typing import Any

__all__ = ("build_and_run_agent",)

logger = logging.getLogger(__name__)


def _make_action_tool(action_name: str) -> Any:
    """Создаёт LangChain tool из зарегистрированного action."""
    import asyncio

    from langchain_core.tools import StructuredTool

    from src.dsl.commands.registry import action_handler_registry
    from src.schemas.invocation import ActionCommandSchema

    async def _run_action(**kwargs: Any) -> str:
        command = ActionCommandSchema(
            action=action_name, payload=kwargs, meta={"source": "ai_agent"}
        )
        result = await action_handler_registry.dispatch(command)
        if hasattr(result, "model_dump"):
            return str(result.model_dump(mode="json"))
        return str(result)

    def _sync_run(**kwargs: Any) -> str:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _run_action(**kwargs)).result()
        return asyncio.run(_run_action(**kwargs))

    return StructuredTool.from_function(
        func=_sync_run,
        coroutine=_run_action,
        name=action_name.replace(".", "_"),
        description=f"Выполняет action '{action_name}' через ActionHandlerRegistry",
    )


async def build_and_run_agent(prompt: str, tool_actions: list[str]) -> dict[str, Any]:
    """Строит и запускает LangGraph-агента.

    Args:
        prompt: Задача для агента.
        tool_actions: Список имён actions, доступных как tools.

    Returns:
        Результат работы агента.
    """
    try:
        from langchain_community.chat_models import ChatOpenAI
        from langgraph.prebuilt import create_react_agent

        tools = [_make_action_tool(action) for action in tool_actions]

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        agent = create_react_agent(llm, tools)

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": prompt}]}
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
        logger.warning("LangGraph не доступен: %s", exc)
        return {"error": f"Зависимости не установлены: {exc}"}
    except Exception as exc:
        logger.error("Agent execution error: %s", exc, exc_info=True)
        return {"error": str(exc)}
