"""Execution Ledger — immutable audit trail для agent tool calls (Wave 3 #20)."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("ExecutionLedger", "ExecutionRecord", "get_execution_ledger")


@dataclass(slots=True)
class ExecutionRecord:
    """Immutable record одного tool execution.

    Все атрибуты immutable после создания (use ``frozen=True``-style через
    только dataclass без setter mutations).
    """

    execution_id: str
    agent: str
    tenant_id: str
    tool: str
    arguments: dict[str, Any]
    result: Any = None
    approved_by: str | None = None
    approval_record_id: str | None = None
    trace_id: str = ""
    timestamp: float = 0.0
    duration_ms: float = 0.0
    error: str | None = None
    status: str = "success"  # "success" | "failed" | "denied"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "agent": self.agent,
            "tenant_id": self.tenant_id,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "result": self.result,
            "approved_by": self.approved_by,
            "approval_record_id": self.approval_record_id,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


class ExecutionLedger:
    """In-memory ledger (production → append-only DB/S3)."""

    def __init__(self) -> None:
        self._records: list[ExecutionRecord] = []

    def record(
        self,
        *,
        agent: str,
        tenant_id: str,
        tool: str,
        arguments: dict[str, Any],
        result: Any = None,
        approved_by: str | None = None,
        approval_record_id: str | None = None,
        trace_id: str = "",
        duration_ms: float = 0.0,
        error: str | None = None,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionRecord:
        """Append new execution record."""
        rec = ExecutionRecord(
            execution_id=str(uuid.uuid4()),
            agent=agent,
            tenant_id=tenant_id,
            tool=tool,
            arguments=dict(arguments),
            result=result,
            approved_by=approved_by,
            approval_record_id=approval_record_id,
            trace_id=trace_id,
            timestamp=time.time(),
            duration_ms=duration_ms,
            error=error,
            status=status,
            metadata=metadata or {},
        )
        self._records.append(rec)
        return rec

    def list_for_agent(self, agent: str) -> list[ExecutionRecord]:
        return [r for r in self._records if r.agent == agent]

    def list_for_tenant(self, tenant_id: str) -> list[ExecutionRecord]:
        return [r for r in self._records if r.tenant_id == tenant_id]

    def list_for_tool(self, tool: str) -> list[ExecutionRecord]:
        return [r for r in self._records if r.tool == tool]

    def size(self) -> int:
        return len(self._records)


_ledger: ExecutionLedger | None = None


def get_execution_ledger() -> ExecutionLedger:
    global _ledger
    if _ledger is None:
        _ledger = ExecutionLedger()
    return _ledger


def reset_execution_ledger() -> None:
    global _ledger
    _ledger = None
