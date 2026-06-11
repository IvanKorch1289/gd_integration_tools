from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.interfaces.ai_clients import AISanitizerProtocol

from src.backend.core.logging import get_logger

logger = get_logger(__name__)


class WebMethodsMixin:
    """public web methods (search_web, parse_webpage) для AIAgentService. S54 W2 extraction."""

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
    _maybe_augment_with_rag: Any
    _get_metrics_service: Any
    _resolve_rag_service: Any
    _resolve_authz_gateway: Any
    __slots__ = ()

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
