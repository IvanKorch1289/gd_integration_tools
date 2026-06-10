from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol
from src.backend.core.logging import get_logger

_logger = get_logger("core.security.authorization_gateway")

class AuditMixin:
    """audit emission helper для AuthorizationGateway. S60 W4 extraction."""

    __slots__ = ()

    def _emit_audit(self, decision: AuthorizationDecision) -> None:
        """Эмиссия ``authorization.decision`` event (best-effort)."""
        if self._audit is None:
            return
        try:
            self._audit(
                {
                    "event": "authorization.decision",
                    "correlation_id": decision.correlation_id,
                    "principal": decision.principal,
                    "resource": decision.resource,
                    "action": decision.action,
                    "outcome": "allow" if decision.allowed else "deny",
                    "reasons": [
                        {"source": r.source, "outcome": r.outcome, "detail": r.detail}
                        for r in decision.reasons
                    ],
                }
            )
        except Exception as _:
            _logger.exception("AuthorizationGateway audit_callback failed")

