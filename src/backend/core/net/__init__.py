"""Сетевые утилиты ядра.

Содержит :class:`OutboundHttpClient` — единственный санкционированный
способ исходящих ``:external`` HTTP-запросов (V15 R-V15-5). Все
``httpx.AsyncClient`` напрямую с capability-меткой ``:external``
запрещены — ловит CI-gate ``tools/check_waf_coverage.py``.
"""

from src.backend.core.net.http_utils import ensure_url_protocol, generate_link_page
from src.backend.core.net.outbound_http import OutboundHttpClient
from src.backend.core.net.waf import (
    WafBypassError,
    WafDecision,
    WafPolicy,
    build_default_policy,
)

__all__ = (
    "OutboundHttpClient",
    "WafBypassError",
    "WafDecision",
    "WafPolicy",
    "build_default_policy",
    "ensure_url_protocol",
    "generate_link_page",
)
