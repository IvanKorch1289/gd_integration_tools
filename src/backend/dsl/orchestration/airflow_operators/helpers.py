from __future__ import annotations
import asyncio
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_log = get_logger(__name__)

# Property name для branch decision (consumed by BranchSelector / routing logic).
BRANCH_DECISION_PROPERTY = "branch.decision"
# Sentinel: operator решил "skip downstream" (no follow-up tasks).
BRANCH_SKIP_VALUE = "__skip__"

# Type alias: branch resolver returns task/branch name (or BRANCH_SKIP_VALUE).
BranchResolver = Callable[[Exchange[Any]], str | Awaitable[str]]
Predicate = Callable[[Exchange[Any]], bool | Awaitable[bool]]

# ── BranchPythonOperator ─────────────────────────────────────────────

def _default_latest_checker(exchange: Exchange[Any]) -> bool:
    """Default: check ``is_latest_run`` header (set by orchestrator)."""
    return bool(exchange.in_message.get_header("is_latest_run", default=True))

