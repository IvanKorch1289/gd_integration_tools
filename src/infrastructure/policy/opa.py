"""OPA client — декларативные data-level policy через REST API.

Deny-by-default при недоступности OPA сервиса (fail-closed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

__all__ = ("OPAClient", "PolicyDecision")

logger = logging.getLogger("policy.opa")


@dataclass(slots=True)
class PolicyDecision:
    allow: bool
    reasons: list[str]


class OPAClient:
    """HTTP-клиент к OPA (typically http://localhost:8181)."""

    def __init__(self, base_url: str = "http://localhost:8181", *, timeout: float = 1.5) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def query(self, policy: str, input_doc: dict[str, Any]) -> PolicyDecision:
        """POST /v1/data/<policy> с `input_doc`; возвращает PolicyDecision.

        ``policy`` — path вроде ``routes/orders/read`` (точки → слэши).
        """
        import httpx

        path = "/v1/data/" + policy.replace(".", "/")
        try:
            async with httpx.AsyncClient(http2=True, timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}{path}", json={"input": input_doc})
                if resp.status_code != 200:
                    logger.warning("OPA non-200 [%s]: %s", resp.status_code, resp.text)
                    return PolicyDecision(allow=False, reasons=[f"opa_status_{resp.status_code}"])
                result = resp.json().get("result", {})
                allow = bool(result.get("allow", False))
                reasons = result.get("reasons", []) or []
                return PolicyDecision(allow=allow, reasons=list(reasons))
        except Exception as exc:
            # Fail-closed: при ошибке сети → deny.
            logger.error("OPA connection failed (deny-by-default): %s", exc)
            return PolicyDecision(allow=False, reasons=["opa_unavailable"])
