"""AI-сервис: мульти-провайдерный (Perplexity, HuggingFace, OpenWebUI).

Все данные маскируются AIDataSanitizer перед отправкой в LLM.
Поддерживает fallback-chain: если основной провайдер недоступен,
используется следующий по приоритету.
"""

import logging
from typing import Any

from src.infrastructure.security.ai_sanitizer import AIDataSanitizer, get_ai_sanitizer

__all__ = ("AIAgentService", "get_ai_agent_service")

logger = logging.getLogger(__name__)


class AIAgentService:
    """Сервис для AI-операций с маскировкой PII."""

    def __init__(self) -> None:
        from src.core.config.ai_settings import (
            AIProvidersSettings,
            HuggingFaceSettings,
            OpenWebUISettings,
            PerplexitySettings,
        )
        from src.core.config.settings import settings

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
        from src.infrastructure.external_apis.http_client import (
            get_http_client_dependency,
        )

        return get_http_client_dependency()

    # ------------------------------------------------------------------
    #  Провайдеры
    # ------------------------------------------------------------------

    async def _post_provider(
        self, *, url: str, headers: dict[str, str], payload: dict[str, Any]
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

    def _build_auth_headers(
        self, api_key: str | None, *, use_waf: bool = False
    ) -> dict[str, str]:
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
        url = (
            self._waf_url
            if self._perplexity.use_waf
            else f"{self._perplexity.base_url}/chat/completions"
        )
        headers = self._build_auth_headers(
            self._perplexity.api_key, use_waf=self._perplexity.use_waf
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
                "max_new_tokens": kwargs.get(
                    "max_tokens", self._huggingface.max_tokens
                ),
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
            result = await client.make_request(
                method="GET", url=self._waf_url, headers=headers
            )
            html_content = result if isinstance(result, str) else str(result)

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_content, "html.parser")

            links = []
            for a_tag in soup.find_all("a", href=True)[:50]:
                links.append(
                    {"text": a_tag.get_text(strip=True), "href": a_tag["href"]}
                )

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
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Чат с LLM через мульти-провайдерную архитектуру.

        Данные маскируются перед отправкой, восстанавливаются после.
        При недоступности провайдера — fallback на следующий.
        Каждый успешный ответ автоматически сохраняется в
        ``AIFeedbackService`` для последующей разметки оператором.

        Args:
            messages: [{role, content}].
            model: Идентификатор модели.
            provider: Конкретный провайдер (или fallback-chain).
            session_id: Идентификатор сессии (для feedback).
            metadata: Дополнительные поля в feedback (tenant_id и т.д.).

        Returns:
            Ответ LLM с восстановленными PII. Дополнительно в ответ
            добавляется ``feedback_id`` — идентификатор записи
            в ``AIFeedbackService`` (для кнопок ✅/❌ на стороне UI).
        """
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

                feedback_id = await self._record_feedback(
                    messages=messages,
                    response=restored,
                    agent_id=f"chat:{prov_name}",
                    session_id=session_id,
                    metadata={
                        **(metadata or {}),
                        "model": model,
                        "provider": prov_name,
                    },
                )

                return {
                    "success": True,
                    "content": restored,
                    "provider": prov_name,
                    "model": model,
                    "feedback_id": feedback_id,
                }
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

    @staticmethod
    def _get_metrics_service() -> Any:
        """Возвращает ``AgentMetricsService`` или ``None`` при сбое.

        Отделено в отдельный метод, чтобы тесты без FastAPI
        и ``prometheus_client`` не падали при импорте сервиса.

        Returns:
            ``AgentMetricsService`` либо ``None``.
        """
        try:
            from src.services.ai.metrics import get_agent_metrics_service

            return get_agent_metrics_service()
        except Exception:
            return None

    async def run_agent(
        self,
        prompt: str,
        tools: list[str] | None = None,
        *,
        agent_id: str = "default",
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Запуск AI-агента с маскировкой PII.

        После успешного ответа автоматически сохраняет результат
        в ``AIFeedbackService`` для последующей разметки оператором.

        Args:
            prompt: Текст задачи.
            tools: Список actions, доступных агенту.
            agent_id: Логический идентификатор агента (для feedback).
            session_id: Идентификатор сессии (для feedback).
            metadata: Дополнительные поля в feedback.

        Returns:
            Результат работы агента. В поле ``feedback_id`` —
            идентификатор записи feedback для кнопок оценки в UI.
        """
        sanitized = self._sanitizer.sanitize_text(prompt)

        try:
            from src.services.ai.ai_graph import build_and_run_agent

            result = await build_and_run_agent(
                prompt=sanitized.sanitized, tool_actions=tools or []
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
            from src.services.ai.feedback import get_ai_feedback_service

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

    @staticmethod
    def _extract_agent_response(result: Any) -> str:
        """Извлекает текст ответа из результата ``build_and_run_agent``.

        Результат может быть dict (с ключом ``response``), строкой
        или произвольной структурой — приводим к строковому представлению.

        Args:
            result: Значение, возвращённое из ``ai_graph``.

        Returns:
            Текст ответа для сохранения в feedback.
        """
        if isinstance(result, dict):
            return str(result.get("response") or result.get("data") or result)
        return str(result)


_ai_agent_service_instance = AIAgentService()


def get_ai_agent_service() -> AIAgentService:
    """Фабрика AI-сервиса."""
    return _ai_agent_service_instance
