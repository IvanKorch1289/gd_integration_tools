"""Audit backend interfaces for core/sinks (ADR-0071).

Protocol definition avoids layer violation: core/audit/ does not import services/.
"""

from __future__ import annotations

from typing import Any, Protocol


class AuditBackend(Protocol):
    """Backend для ClickHouse audit writes."""

    async def emit(
        self,
        event: str,
        actor: str,
        resource: str,
        action: str,
        outcome: str,
        severity: str,
        correlation_id: str | None,
        tenant_id: str | None,
        route_name: str | None,
        details: dict[str, Any],
    ) -> None: ...


class LangfuseCallbackBackend(Protocol):
    """Backend для Langfuse trace writes."""

    @property
    def _generation_id(self) -> Any: ...

    def flush(self, generation_id: Any, event: dict[str, Any]) -> None: ...
