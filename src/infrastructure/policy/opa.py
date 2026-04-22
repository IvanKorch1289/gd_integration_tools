"""OPA client — декларативные data-level policy через REST API.

Deny-by-default при недоступности OPA сервиса (fail-closed).

IL-CRIT1.4b: до этой фазы `OPAClient.query()` создавал новый
`httpx.AsyncClient` на **каждый запрос** (`async with httpx.AsyncClient(...)`).
Под нагрузкой это быстро исчерпывало файловые дескрипторы и создавало
сотни лишних TCP-коннектов в секунду. Теперь клиент — singleton с
pool-параметрами (HTTP/2 + keepalive), управляется через
`InfrastructureClient` lifecycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx


__all__ = ("OPAClient", "PolicyDecision")

logger = logging.getLogger("policy.opa")


@dataclass(slots=True)
class PolicyDecision:
    allow: bool
    reasons: list[str]


class OPAClient:
    """HTTP-клиент к OPA (typically http://localhost:8181).

    Lazy-инициализация одного `httpx.AsyncClient` на весь life-of-process.
    Graceful shutdown через `close()`. Connection pool + HTTP/2 снижают
    нагрузку на OPA-сервис и устраняют exhaustion файловых дескрипторов.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8181",
        *,
        timeout: float = 1.5,
        max_connections: int = 32,
        max_keepalive_connections: int = 16,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive_connections
        self._client: "httpx.AsyncClient | None" = None

    def _ensure_client(self) -> "httpx.AsyncClient":
        """Lazy-init singleton httpx-клиента."""
        if self._client is None:
            import httpx

            limits = httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_keepalive,
                keepalive_expiry=30.0,
            )
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                http2=True,
                timeout=self.timeout,
                limits=limits,
            )
            logger.debug(
                "OPA client initialized (pool=%d/%d, http2=True)",
                self._max_connections,
                self._max_keepalive,
            )
        return self._client

    async def close(self) -> None:
        """Graceful shutdown (вызывается из ConnectorRegistry.stop_all)."""
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    async def query(
        self, policy: str, input_doc: dict[str, Any]
    ) -> PolicyDecision:
        """POST /v1/data/<policy> с `input_doc`; возвращает PolicyDecision.

        ``policy`` — path вроде ``routes/orders/read`` (точки → слэши).
        Fail-closed: любые ошибки сети / 5xx → deny.
        """
        path = "/v1/data/" + policy.replace(".", "/")
        client = self._ensure_client()
        try:
            resp = await client.post(path, json={"input": input_doc})
            if resp.status_code != 200:
                logger.warning(
                    "OPA non-200 [%s]: %s", resp.status_code, resp.text[:200]
                )
                return PolicyDecision(
                    allow=False, reasons=[f"opa_status_{resp.status_code}"]
                )
            result = resp.json().get("result", {})
            allow = bool(result.get("allow", False))
            reasons = result.get("reasons", []) or []
            return PolicyDecision(allow=allow, reasons=list(reasons))
        except Exception as exc:  # noqa: BLE001
            # Fail-closed: при ошибке сети → deny.
            logger.error("OPA connection failed (deny-by-default): %s", exc)
            return PolicyDecision(allow=False, reasons=["opa_unavailable"])
