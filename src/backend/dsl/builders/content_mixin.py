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
from collections.abc import Callable
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
    "MulticastEIPProcessor",
    "RecipientListEIPProcessor",
    "WireTapEIPProcessor",
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
            with urllib.request.urlopen(  # noqa: S310
                _resolve(self.source, exchange), timeout=5
            ) as r:
                raw = r.read().decode("utf-8")
            try:
                return json.loads(raw)
            except ValueError, TypeError:
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
    """Wire Tap EIP — record tap, fire-and-forget if async."""

    side_effect: ClassVar[Any] = "TAP"
    compensatable: ClassVar[bool] = True

    def __init__(
        self, *, sink: str, async_: bool = True, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"eip.wire_tap({sink})")
        self.sink, self.async_ = sink, async_

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Записать copy exchange в ``_wire_taps`` (fire-and-forget для async)."""
        taps = list(exchange.properties.get("_wire_taps") or [])
        taps.append({"sink": self.sink, "async": self.async_})
        exchange.properties["_wire_taps"] = taps
        if self.async_:
            _TAP_EXECUTOR.submit(lambda: None)
        else:
            return  # sink resolved downstream


class MulticastEIPProcessor(BaseProcessor):
    """Multicast EIP — fan-out to a list of sinks."""

    side_effect: ClassVar[Any] = "PUBLISH"
    compensatable: ClassVar[bool] = False

    def __init__(
        self, *, sinks: list[str], parallel: bool = True, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"eip.multicast({len(sinks)} sinks)")
        self.sinks, self.parallel = list(sinks), parallel

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.properties["_multicast_sinks"] = list(self.sinks)
        exchange.properties["_multicast_parallel"] = self.parallel


class RecipientListEIPProcessor(BaseProcessor):
    """Recipient List EIP — static or callable recipient list."""

    side_effect: ClassVar[Any] = "PUBLISH"
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        recipients: list[str] | Callable[[Exchange[Any]], list[str]],
        parallel: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "eip.recipient_list")
        self._recipients, self.parallel = recipients, parallel

    def _resolve_recipients(self, exchange: Exchange[Any]) -> list[str]:
        if callable(self._recipients):
            r = self._recipients(exchange)
            return list(r) if r else []
        return list(self._recipients) if self._recipients else []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.properties["_recipients"] = self._resolve_recipients(exchange)
        exchange.properties["_recipients_parallel"] = self.parallel


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

    def wire_tap(
        self, sink: str, *, async_: bool = True, name: str | None = None
    ) -> RouteBuilder:
        """Wire Tap EIP — copy exchange to ``sink`` (async by default)."""
        return self._add(  # type: ignore[attr-defined]
            WireTapEIPProcessor(sink=sink, async_=async_, name=name)
        )

    def multicast(
        self, sinks: list[str], *, parallel: bool = True, name: str | None = None
    ) -> RouteBuilder:
        """Multicast EIP — fan-out to multiple sinks (parallel by default)."""
        if not sinks:
            return self  # type: ignore[return-value]
        return self._add(  # type: ignore[attr-defined]
            MulticastEIPProcessor(sinks=sinks, parallel=parallel, name=name)
        )

    def recipient_list(
        self,
        recipients: list[str] | Callable[[Exchange[Any]], list[str]],
        *,
        parallel: bool = True,
        name: str | None = None,
    ) -> RouteBuilder:
        """Recipient List EIP — list or callable ``(exchange) -> list``."""
        return self._add(  # type: ignore[attr-defined]
            RecipientListEIPProcessor(
                recipients=recipients, parallel=parallel, name=name
            )
        )
