from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.di.providers.ai import get_ai_sanitizer_provider
    from src.backend.core.di.providers.http import get_http_client_provider
    from src.backend.core.interfaces.ai_clients import AISanitizerProtocol, HttpClientProtocol

from src.backend.core.logging import get_logger

logger = get_logger(__name__)
class HttpProvidersMixin:
    """HTTP/auth + AI provider integrations (Perplexity, HuggingFace, Open WebUI) для AIAgentService. S54 W2 extraction."""

    # State attrs + cross-method hints (S54 W2: class-level annotations for mypy MRO)
    _sanitizer: "AISanitizerProtocol"
    _ai_cfg: Any
    _providers: dict[str, Any]
    _open_webui: Any
    _huggingface: Any
    _perplexity: Any
    _waf_headers: Any
    _waf_url: Any
    _agent_metrics_service: Any
    _agent_tracer: Any
    _agent_redis: Any
    _get_http_client: Any
    _extract_agent_response: Any

    _policy_gate: Any
    _maybe_augment_with_rag: Any

    _resolve_rag_service: Any
    _resolve_authz_gateway: Any
    __slots__ = ()

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

        prompt = "\n".join(
            f"system: {m['content']}"
            if m.get("role") == "system"
            else f"{m['role']}: {m['content']}"
            for m in messages
        )
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

    @staticmethod
    def _get_metrics_service() -> Any:
        """Возвращает ``AgentMetricsService`` или ``None`` при сбое.

        Отделено в отдельный метод, чтобы тесты без FastAPI
        и ``prometheus_client`` не падали при импорте сервиса.

        Returns:
            ``AgentMetricsService`` либо ``None``.
        """
        try:
            from src.backend.services.ai.metrics import get_agent_metrics_service

            return get_agent_metrics_service()
        except Exception as _:
            return None

