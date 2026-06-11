"""AIAgentService package (S54 W2 decomp from ai_agent.py 703 LOC).

19 methods decomposed в 5 mixin files:
- ``http_providers_mixin.py`` (6): HTTP/auth + AI provider integrations
- ``web_methods_mixin.py`` (2): public web methods (search_web, parse_webpage)
- ``agent_orchestration_mixin.py`` (3): agent orchestration (chat, run_agent, _record_feedback)
- ``rag_mixin.py`` (2): RAG integration
- ``policy_mixin.py`` (3): policy/authz gates

Core (__init__ + _get_http_client + _extract_agent_response) остается в __init__.py.

Backward-compat: ``from src.backend.services.ai.ai_agent import AIAgentService, get_ai_agent_service`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.di.providers.ai import get_ai_sanitizer_provider
    from src.backend.core.di.providers.http import get_http_client_provider
    from src.backend.core.interfaces.ai_clients import (
        AISanitizerProtocol,
        HttpClientProtocol,
    )

from src.backend.services.ai.ai_agent.agent_orchestration_mixin import (
    AgentOrchestrationMixin,  # S54 W2: MRO
)
from src.backend.services.ai.ai_agent.http_providers_mixin import (
    HttpProvidersMixin,  # S54 W2: MRO
)
from src.backend.services.ai.ai_agent.policy_mixin import PolicyMixin  # S54 W2: MRO
from src.backend.services.ai.ai_agent.rag_mixin import RagMixin  # S54 W2: MRO
from src.backend.services.ai.ai_agent.web_methods_mixin import (
    WebMethodsMixin,  # S54 W2: MRO
)

__all__ = ("AIAgentService", "get_ai_agent_service")


class AIAgentService(
    HttpProvidersMixin, WebMethodsMixin, AgentOrchestrationMixin, RagMixin, PolicyMixin
):
    """AI Agent Service (5 mixins = 16 methods + 3 core)."""

    # State attrs (S54 W2: class-level annotations for mypy MRO)
    _sanitizer: "AISanitizerProtocol"
    _ai_cfg: Any
    _providers: dict[str, Any]
    _open_webui: Any
    _waf_headers: Any
    _waf_url: Any
    _agent_metrics_service: Any
    _agent_tracer: Any
    _agent_redis: Any

    def __init__(self) -> None:
        from src.backend.core.config.ai import (
            AIProvidersSettings,
            HuggingFaceSettings,
            OpenWebUISettings,
            PerplexitySettings,
        )
        from src.backend.core.config.settings import settings

        self._waf_url = settings.http_base_settings.waf_url
        self._waf_headers = dict(settings.http_base_settings.waf_route_header)

        self._perplexity = PerplexitySettings()
        self._huggingface = HuggingFaceSettings()
        self._open_webui = OpenWebUISettings()
        self._ai_cfg = AIProvidersSettings()

        # Wave 6.3: lazy-провайдер sanitizer + http-клиент через core/di.
        self._sanitizer: AISanitizerProtocol = get_ai_sanitizer_provider()

        self._providers = {
            "perplexity": self._call_perplexity,
            "huggingface": self._call_huggingface,
            "open_webui": self._call_open_webui,
        }

    def _get_http_client(self) -> HttpClientProtocol:
        # Wave 6.3: lazy-резолв через core/di.providers — без прямого
        # импорта infrastructure/*.
        return get_http_client_provider()

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


def get_ai_agent_service() -> AIAgentService:
    """Фабрика AI-сервиса."""
    raise NotImplementedError  # заменяется декоратором
