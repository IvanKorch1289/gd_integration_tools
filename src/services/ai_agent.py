"""AI-сервис: поиск через Perplexity, парсинг через BeautifulSoup, чат через LangChain.

Все HTTP-запросы к внешним AI-сервисам проксируются через WAF
(waf_url + waf_route_header из настроек).
"""

import json
import logging
from typing import Any

from app.core.decorators.singleton import singleton

__all__ = ("AIAgentService", "get_ai_agent_service")

logger = logging.getLogger(__name__)


@singleton
class AIAgentService:
    """Сервис для AI-операций."""

    def __init__(self) -> None:
        from app.core.config.settings import settings
        self._waf_url = settings.http_base_settings.waf_url
        self._waf_headers = dict(settings.http_base_settings.waf_route_header)

    async def search_web(self, query: str, model: str = "sonar") -> dict[str, Any]:
        """Поиск через Perplexity API (проксируется через WAF).

        Args:
            query: Поисковый запрос.
            model: Модель Perplexity (sonar, sonar-pro и т.д.).

        Returns:
            Результат поиска.
        """
        from app.infrastructure.external_apis.http_client import (
            get_http_client_dependency,
        )

        client = get_http_client_dependency()

        headers = {**self._waf_headers, "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": query}],
        }

        try:
            result = await client.make_request(
                method="POST",
                url=self._waf_url,
                headers=headers,
                json=payload,
            )
            return {"success": True, "data": result}
        except Exception as exc:
            logger.error("Perplexity search error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def parse_webpage(self, url: str) -> dict[str, Any]:
        """Парсинг веб-страницы через BeautifulSoup (проксируется через WAF).

        Args:
            url: URL страницы для парсинга.

        Returns:
            Структурированные данные страницы.
        """
        from app.infrastructure.external_apis.http_client import (
            get_http_client_dependency,
        )

        client = get_http_client_dependency()

        headers = {
            **self._waf_headers,
            "X-Target-URL": url,
        }

        try:
            result = await client.make_request(
                method="GET",
                url=self._waf_url,
                headers=headers,
            )

            html_content = result if isinstance(result, str) else str(result)

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_content, "html.parser")

            links = []
            for a_tag in soup.find_all("a", href=True)[:50]:
                links.append({"text": a_tag.get_text(strip=True), "href": a_tag["href"]})

            return {
                "success": True,
                "title": soup.title.string if soup.title else None,
                "text": soup.get_text(separator=" ", strip=True)[:5000],
                "links": links,
            }
        except Exception as exc:
            logger.error("Webpage parse error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "default",
    ) -> dict[str, Any]:
        """Чат с LLM через LangChain (проксируется через WAF).

        Args:
            messages: Список сообщений [{role, content}].
            model: Идентификатор модели.

        Returns:
            Ответ LLM.
        """
        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

            lc_messages = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                elif role == "assistant":
                    lc_messages.append(AIMessage(content=content))
                else:
                    lc_messages.append(HumanMessage(content=content))

            from langchain_community.chat_models import ChatOpenAI

            llm = ChatOpenAI(model=model)
            response = await llm.ainvoke(lc_messages)

            return {
                "success": True,
                "content": response.content,
                "model": model,
            }
        except ImportError:
            return {
                "success": False,
                "error": "langchain не установлен. Добавьте langchain-core и langchain-community.",
            }
        except Exception as exc:
            logger.error("LLM chat error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def run_agent(
        self,
        prompt: str,
        tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Запуск AI-агента с инструментами через LangGraph.

        Args:
            prompt: Текст задачи для агента.
            tools: Список имён actions, доступных агенту.

        Returns:
            Результат работы агента.
        """
        try:
            from app.services.ai_graph import build_and_run_agent

            result = await build_and_run_agent(prompt=prompt, tool_actions=tools or [])
            return {"success": True, "data": result}
        except ImportError:
            return {
                "success": False,
                "error": "langgraph не установлен. Добавьте langgraph.",
            }
        except Exception as exc:
            logger.error("Agent run error: %s", exc)
            return {"success": False, "error": str(exc)}


def get_ai_agent_service() -> AIAgentService:
    """Фабрика AI-сервиса."""
    return AIAgentService()
