"""Low-level probes для processor health checks (W9 P2-13 Phase 4).

W9 P2-13 Phase 4 (cycle 153): извлечено из ``services/ops/health.py``
(609 LOC god-module). Содержит ``_http_get`` и ``_tcp_connect`` utilities —
async probes для HTTP/TCP-level checks.

Использует ``OutboundHttpClient`` для WAF compliance + ``safe_wait_for`` для
timeout/reraise guarantees.

Back-compat: ``services/ops/health.py`` (file) продолжает re-export через
thin ``__init__.py`` shim (см. ADR-0329).
"""

from __future__ import annotations

import asyncio

from src.backend.core.async_utils.safe_wait import safe_wait_for


async def _http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """Perform HTTP GET and return (status_code, text).

    Uses OutboundHttpClient for WAF compliance.

    Args:
        url: Target URL.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (status_code, response_text).

    """
    from src.backend.core.net.outbound_http import OutboundHttpClient

    async with OutboundHttpClient(timeout=timeout) as client:  # type: ignore[arg-type]  # R2.MYPY: float → Timeout
        resp = await client.get(url)
        return resp.status_code, resp.text


async def _tcp_connect(host: str, port: int, timeout: float = 5.0) -> None:
    """Установить TCP-соединение и сразу закрыть."""
    _, writer = await safe_wait_for(
        asyncio.open_connection(host, port), timeout=timeout, operation="_tcp_connect"
    )  # type: ignore[misc]  # reraise=True гарантирует non-None
    writer.close()
    await writer.wait_closed()
