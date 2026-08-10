"""EIPContentMixin — 4 EIP DSL methods for RouteBuilder (S39 W2).

Adds ``enrich`` / ``wire_tap`` / ``multicast`` / ``recipient_list``
(Enterprise Integration Patterns) as chainable methods. Named
``EIPContentMixin`` (not ``ContentMixin``) to avoid clashing with the
legacy :class:`dsl.builders.content.ContentMixin` already in the MRO.
Stdlib-only; idempotent; supports ``${exchange.path}`` placeholder
substitution for HTTP enrichment URLs.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "EIPContentMixin",
    "EnrichEIPProcessor",
)

_TAP_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="eip-tap")
atexit.register(_TAP_EXECUTOR.shutdown, wait=True)
_PH_RE = re.compile(r"\$\{exchange\.([a-zA-Z0-9_.]+)\}")


def _resolve(template: str, exchange: Exchange[Any]) -> str:
    """Substitute ``${exchange.path}`` placeholders from in_message.body."""

    def _r(m: re.Match[str]) -> str:
        node: Any = exchange.in_message.body
        for p in m.group(1).split("."):
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                return m.group(0)
        return str(node)

    return _PH_RE.sub(_r, template)


# ─── Marker processors ────────────────────────────────────────────────


class EnrichEIPProcessor(BaseProcessor):
    """Content Enricher EIP — http / static / function strategies."""

    side_effect: ClassVar[Any] = "READ"
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        strategy: str,
        field: str,
        source: str | None = None,
        value: Any = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"eip.enrich({strategy}:{field})")
        self.strategy, self.field = strategy, field
        self.source, self.value = source, value

    def _fetch(self, exchange: Exchange[Any]) -> Any:
        if self.strategy == "http":
            assert self.source, "http strategy requires source URL"
            with urllib.request.urlopen(
                _resolve(self.source, exchange), timeout=5
            ) as r:
                raw = r.read().decode("utf-8")
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return {"_raw": raw}
        if self.strategy == "static":
            return self.value
        if self.strategy == "function":
            assert callable(self.value), "function strategy requires callable"
            return self.value(exchange)
        raise ValueError(f"unknown enrich strategy: {self.strategy!r}")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обогатить exchange.properties[self.field] через async-to-thread fetch."""
        exchange.properties[self.field] = await asyncio.to_thread(self._fetch, exchange)


class WireTapEIPProcessor(BaseProcessor):
    """Wire Tap EIP — record tap, fire-and-forget if async.

    Cycle 45: REMOVED from this file. The shadowing implementations
    (WireTapEIPProcessor, MulticastEIPProcessor, RecipientListEIPProcessor)
    stored properties without dispatching, shadowing the working
    implementations in ContentMixin via MRO ordering.

    The canonical implementations live in:
    - src/backend/dsl/engine/processors/eip/flow_control/wire_tap.py
    - src/backend/dsl/engine/processors/eip/routing/multicast.py
    - src/backend/dsl/engine/processors/eip/routing/recipient_list.py

    These are used by the working content.py:wire_tap/multicast/recipient_list
    methods that take MRO position 10 (after this EIP mixin at 9).
    """


# ─── Mixin ────────────────────────────────────────────────────────────


class EIPContentMixin:
    """RouteBuilder mixin for 4 EIP DSL methods (S39 W2)."""

    __slots__ = ()

    def content_enrich(
        self,
        *,
        strategy: str = "http",
        field: str = "enrichment",
        source: str | None = None,
        value: Any = None,
        name: str | None = None,
    ) -> RouteBuilder:
        """Content Enricher EIP — http/static/function strategies.

        Note: renamed from `enrich` to avoid conflict with
        ``EIPMixin.enrich(action=...)`` from eip.py. Use this method
        for content-based enrichment (EIP pattern), use EIPMixin's
        `enrich(action=...)` for action-based enrichment.
        """
        return self._add(  # type: ignore[attr-defined]
            EnrichEIPProcessor(
                strategy=strategy, field=field, source=source, value=value, name=name
            )
        )

    # NOTE (cycle 45): wire_tap, multicast, recipient_list methods were
    # REMOVED from this mixin. They shadowed the working implementations
    # in ContentMixin via MRO ordering (this EIP mixin is at MRO position 9,
    # ContentMixin at position 10). See content.py for the canonical
    # implementations that are now resolved.
    #
    # The legacy `WireTapEIPProcessor` / `MulticastEIPProcessor` /
    # `RecipientListEIPProcessor` classes were also removed (they only
    # stored properties without dispatching — true no-op routing).
