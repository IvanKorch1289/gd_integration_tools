"""AI-сервис: мульти-провайдерный (Perplexity, HuggingFace, OpenWebUI).

Все данные маскируются AIDataSanitizer перед отправкой в LLM.
Поддерживает fallback-chain: если основной провайдер недоступен,
используется следующий по приоритету.
"""

import logging
from typing import Any

from app.core.decorators.singleton import singleton
from app.core.security.ai_sanitizer import AIDataSanitizer, get_ai_sanitizer

__all__ = ("AIAgentService", "get_ai_agent_service")

logger = logging.getLogger(__name__)


@singleton
class AIAgentService:
    """Сервис для AI-операций с маскировкой PII."""

    def __init__(self) -> None:
        from app.core.config.ai_settings import (
            AIProvidersSettings,
            HuggingFaceSettings,
            OpenWebUISettings,
            PerplexitySettings,
        )
        from app.core.config.settings import settings

        self._waf_url = settings.http_base_settings.waf_url
        self._waf_headers = dict(settings.http_base_settings.waf_route_header)

        self._perplexity = PerplexitySettings()
        self._huggingface = HuggingFaceSettings()
        self._open_webui = OpenWebUISettings()
        self._ai_cfg = AIProvidersSettings()

        self._sanitizer: AIDataSanitizer = get_ai_sanitizer()

        self._providers = {
            "perplexity": self._call_perplexity,
            "huggingface": self._call_huggingface,
            "open_webui": self._call_open_webui,
        }

    def _get_http_client(self):
        from app.infrastructure.external_apis.http_client import (
            get_http_client_dependency,
        )
        return get_http_client_dependency()

    # ------------------------------------------------------------------
    #  Провайдеры
    # ------------------------------------------------------------------

    async def _post_provider(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Общий POST-вызов с единой политикой таймаутов."""
        client = self._get_http_client()
        return await client.make_request(
            method="POST",
            url=url,
            headers=headers,
            json=payload,
            connect_timeout=self._ai_cfg.connect_timeout,
            read_timeout=self._ai_cfg.read_timeout,
            total_timeout=self._ai_cfg.connect_timeout + self._ai_cfg.read_timeout,
        )

    def _build_auth_headers(self, api_key: str | None, *, use_waf: bool = False) -> dict[str, str]:
        """Формирует Content-Type + Authorization (с WAF-перекрытием при необходимости)."""
        headers: dict[str, str] = {}
        if use_waf:
            headers.update(self._waf_headers)
        headers["Content-Type"] = "application/json"
        if not use_waf and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def _call_perplexity(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        """Вызов Perplexity API."""
        model = kwargs.get("model", self._perplexity.model)
        url = self._waf_url if self._perplexity.use_waf else f"{self._perplexity.base_url}/chat/completions"
        headers = self._build_auth_headers(
            self._perplexity.api_key, use_waf=self._perplexity.use_waf,
        )
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self._perplexity.max_tokens),
            "temperature": kwargs.get("temperature", self._perplexity.temperature),
        }
        return await self._post_provider(url=url, headers=headers, payload=payload)

    async def _call_huggingface(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        """Вызов HuggingFace Inference API."""
        model = kwargs.get("model", self._huggingface.model)
        url = f"{self._huggingface.base_url}/{model}"
        headers = self._build_auth_headers(self._huggingface.api_key)

        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": kwargs.get("max_tokens", self._huggingface.max_tokens),
                "temperature": kwargs.get("temperature", self._huggingface.temperature),
            },
        }
        return await self._post_provider(url=url, headers=headers, payload=payload)

    async def _call_open_webui(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        """Вызов внутреннего OpenWebUI сервера."""
        model = kwargs.get("model", self._open_webui.model)
        url = f"{self._open_webui.base_url}/api/chat/completions"
        headers = self._build_auth_headers(self._open_webui.api_key)
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self._open_webui.max_tokens),
            "temperature": kwargs.get("temperature", self._open_webui.temperature),
        }
        return await self._post_provider(url=url, headers=headers, payload=payload)

    # ------------------------------------------------------------------
    #  Публичные методы
    # ------------------------------------------------------------------

    async def search_web(self, query: str, model: str = "sonar") -> dict[str, Any]:
        """Поиск через Perplexity API с маскировкой PII.

        Args:
            query: Поисковый запрос.
            model: Модель Perplexity.

        Returns:
            Результат поиска с восстановленными данными.
        """
        sanitized = self._sanitizer.sanitize_text(query)
        messages = [{"role": "user", "content": sanitized.sanitized}]

        try:
            result = await self._call_perplexity(messages, model=model)
            return {"success": True, "data": result}
        except Exception as exc:
            logger.error("Perplexity search error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def parse_webpage(self, url: str) -> dict[str, Any]:
        """Парсинг веб-страницы через BeautifulSoup (через WAF)."""
        client = self._get_http_client()
        headers = {**self._waf_headers, "X-Target-URL": url}

        try:
            result = await client.make_request(method="GET", url=self._waf_url, headers=headers)
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
        provider: str | None = None,
    ) -> dict[str, Any]:
        """Чат с LLM через мульти-провайдерную архитектуру.

        Данные маскируются перед отправкой, восстанавливаются после.
        При недоступности провайдера — fallback на следующий.

        Args:
            messages: [{role, content}].
            model: Идентификатор модели.
            provider: Конкретный провайдер (или fallback-chain).

        Returns:
            Ответ LLM с восстановленными PII.
        """
        sanitized_msgs, mapping = self._sanitizer.sanitize_messages(messages)

        chain = [provider] if provider else self._ai_cfg.fallback_chain
        last_error: str | None = None

        for prov_name in chain:
            call_fn = self._providers.get(prov_name)
            if call_fn is None:
                continue

            try:
                result = await call_fn(sanitized_msgs, model=model)

                content = ""
                if isinstance(result, dict):
                    choices = result.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                    elif "generated_text" in result:
                        content = result["generated_text"]
                    elif isinstance(result.get("data"), str):
                        content = result["data"]

                restored = self._sanitizer.restore_text(content, mapping)

                return {
                    "success": True,
                    "content": restored,
                    "provider": prov_name,
                    "model": model,
                }
            except Exception as exc:
                last_error = f"{prov_name}: {exc}"
                logger.warning("AI provider '%s' failed: %s", prov_name, exc)

        return {"success": False, "error": f"All providers failed. Last: {last_error}"}

    async def run_agent(
        self,
        prompt: str,
        tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Запуск AI-агента с маскировкой PII.

        Args:
            prompt: Текст задачи.
            tools: Список actions, доступных агенту.

        Returns:
            Результат работы агента.
        """
        sanitized = self._sanitizer.sanitize_text(prompt)

        try:
            from app.services.ai_graph import build_and_run_agent

            result = await build_and_run_agent(
                prompt=sanitized.sanitized, tool_actions=tools or []
            )

            if isinstance(result, str):
                result = sanitized.restore(result)

            return {"success": True, "data": result}
        except ImportError:
            return {"success": False, "error": "langgraph не установлен."}
        except Exception as exc:
            logger.error("Agent run error: %s", exc)
            return {"success": False, "error": str(exc)}


def get_ai_agent_service() -> AIAgentService:
    """Фабрика AI-сервиса."""
    return AIAgentService()
