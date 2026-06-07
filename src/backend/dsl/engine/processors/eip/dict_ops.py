"""Pydash-based EIP processors для deep dict operations (S57 W2).

Apache Camel EIP / DSL extension: deep access, transform, omit, pick.
Uses :mod:`pydash` (Sprint 5 dep, S57 W2 adoption) для declarative
dict operations.

Pydash 8.0 API (post-rename от lodash convention):
* ``pydash.get(obj, path, default)`` — top-level.
* ``pydash.objects.set_(obj, path, value)`` — deep set с auto-create intermediate dicts.
* ``pydash.objects.unset(obj, path)`` — deep remove по path.
* ``pydash.objects.omit(obj, *keys)`` — top-level key removal.
* ``pydash.objects.omit_by(obj, predicate)`` — remove keys matching predicate.
* ``pydash.objects.pick(obj, *keys)`` — top-level whitelist projection.
* ``pydash.objects.merge(*objs)`` — deep recursive merge.

Use cases (DSL pipelines):
* :class:`PydashGetProcessor` — extract nested field с default fallback.
* :class:`PydashSetProcessor` — установить nested field.
* :class:`PydashOmitProcessor` — strip чувствительных полей.
* :class:`PydashPickProcessor` — whitelist projection.
* :class:`PydashMergeProcessor` — deep merge defaults в body.

Использование::

    from src.backend.dsl.engine.processors.eip.dict_ops import (
        PydashGetProcessor,
        PydashOmitProcessor,
    )

    .process(PydashGetProcessor(path="customer.email", default="anonymous"))
    .process(PydashOmitProcessor(fields=["password", "ssn", "card_number"]))

Thread-safe: pydash функции pure; processor instances immutable post-construction.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Sequence
from typing import Any, ClassVar

import pydash
import pydash.objects

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = (
    "PydashGetProcessor",
    "PydashMergeProcessor",
    "PydashOmitProcessor",
    "PydashPickProcessor",
    "PydashSetProcessor",
)

_log = logging.getLogger(__name__)


# ── PydashGetProcessor ──────────────────────────────────────────────


class PydashGetProcessor(BaseProcessor):
    """Extract nested field из body по dotted path с default fallback.

    Args:
        path: dotted path (``"user.profile.email"``) или bracket notation
            (``"users[0].name"`` для list access).
        default: fallback value если path missing / not found.
        write_back: если True — extracted value replaces body (для
            downstream chain). Default False (read-only, body unchanged).
        property_name: имя property для сохранения extracted value
            (default ``extracted_value``). Ignored if ``write_back=True``.
        name: имя процессора.

    Example::

        PydashGetProcessor(path="customer.email", default="anonymous")
        # body = {"customer": {"email": "a@b.com"}} → property "extracted_value" = "a@b.com"
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        path: str,
        *,
        default: Any = None,
        write_back: bool = False,
        property_name: str = "extracted_value",
        name: str | None = None,
    ) -> None:
        if not path:
            raise ValueError("PydashGetProcessor: path is required")
        super().__init__(name=name or f"pydash_get:{path[:20]}")
        self._path = path
        self._default = default
        self._write_back = write_back
        self._property_name = property_name

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        value = pydash.get(body, self._path, default=self._default)
        exchange.set_property(self._property_name, value)
        _log.debug("PydashGet[%s]: %r", self._path, value)
        if self._write_back:
            exchange.set_out(body=value, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "pydash_get",
            "path": self._path,
            "write_back": self._write_back,
        }


# ── PydashSetProcessor ──────────────────────────────────────────────


class PydashSetProcessor(BaseProcessor):
    """Set nested field в body по dotted path (immutably, per-exchange).

    Args:
        path: dotted path для set (``"user.profile.role"``).
        value: value для set. Может быть callable — будет вызван с
            exchange для dynamic value.
        name: имя процессора.

    Example::

        PydashSetProcessor(path="metadata.source", value="api_v2")
        # body = {} → body = {"metadata": {"source": "api_v2"}}

        PydashSetProcessor(
            path="metadata.processed_at",
            value=lambda ex: ex.get_property("timestamp"),
        )
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, path: str, value: Any, *, name: str | None = None) -> None:
        if not path:
            raise ValueError("PydashSetProcessor: path is required")
        super().__init__(name=name or f"pydash_set:{path[:20]}")
        self._path = path
        self._value = value

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        # Resolve dynamic value (callable принимает exchange).
        resolved = self._value
        if callable(self._value) and not isinstance(self._value, type):
            resolved = self._value(exchange)

        # Defensive copy — НЕ мутируем upstream body (other consumers
        # могут держать reference). pydash.objects.set_ создаёт intermediate dicts.
        new_body = (
            copy.deepcopy(exchange.in_message.body)
            if isinstance(exchange.in_message.body, (dict, list))
            else {}
        )
        pydash.objects.set_(new_body, self._path, resolved)
        exchange.set_out(body=new_body, headers=dict(exchange.in_message.headers))
        _log.debug("PydashSet[%s]: %r", self._path, resolved)

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "pydash_set", "path": self._path}


# ── PydashOmitProcessor ─────────────────────────────────────────────


class PydashOmitProcessor(BaseProcessor):
    """Strip fields из body (security: remove sensitive data перед log/external API).

    Args:
        fields: list of key names / dotted paths для remove.
        deep: если True — recursively remove по any depth (через
            ``pydash.objects.unset`` для каждого path; либо
            ``omit_by`` с isinstance check).
        name: имя процессора.

    Example::

        PydashOmitProcessor(fields=["password", "ssn", "card_number"])
        # body = {"name": "alice", "password": "x", "ssn": "123"} →
        # body = {"name": "alice"}
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self, fields: Sequence[str], *, deep: bool = False, name: str | None = None
    ) -> None:
        if not fields:
            raise ValueError("PydashOmitProcessor: fields must be non-empty")
        super().__init__(name=name or f"pydash_omit:{len(fields)}")
        self._fields = list(fields)
        self._deep = deep

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, dict):
            _log.warning("PydashOmit: body is not a dict, no-op")
            return
        new_body = copy.deepcopy(body)
        if self._deep:
            # Recursively remove top-level keys matching field names
            # (any depth). pydash.objects.omit_by uses predicate для match.
            for field in self._fields:
                new_body = _recursive_omit(new_body, field)
        else:
            new_body = pydash.objects.omit(new_body, self._fields)
        exchange.set_out(body=new_body, headers=dict(exchange.in_message.headers))
        _log.debug(
            "PydashOmit: removed %d fields (deep=%s)", len(self._fields), self._deep
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "pydash_omit", "fields": self._fields, "deep": self._deep}


def _recursive_omit(obj: Any, target_key: str) -> Any:
    """Recursively remove ``target_key`` from any depth в dict структуре.

    Lists traversed; non-dict/non-list values returned as-is.
    """
    if isinstance(obj, dict):
        return {
            k: _recursive_omit(v, target_key) for k, v in obj.items() if k != target_key
        }
    if isinstance(obj, list):
        return [_recursive_omit(item, target_key) for item in obj]
    return obj


# ── PydashPickProcessor ─────────────────────────────────────────────


class PydashPickProcessor(BaseProcessor):
    """Whitelist projection: output только указанных fields.

    Args:
        fields: list of key names для include (всё остальное discarded).
        name: имя процессора.

    Example::

        PydashPickProcessor(fields=["id", "name", "email"])
        # body = {"id": 1, "name": "a", "email": "a@b", "password": "x"} →
        # body = {"id": 1, "name": "a", "email": "a@b"}
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, fields: Sequence[str], *, name: str | None = None) -> None:
        if not fields:
            raise ValueError("PydashPickProcessor: fields must be non-empty")
        super().__init__(name=name or f"pydash_pick:{len(fields)}")
        self._fields = list(fields)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, dict):
            _log.warning("PydashPick: body is not a dict, no-op")
            return
        new_body = pydash.objects.pick(copy.deepcopy(body), self._fields)
        exchange.set_out(body=new_body, headers=dict(exchange.in_message.headers))
        _log.debug("PydashPick: kept %d fields", len(self._fields))

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "pydash_pick", "fields": self._fields}


# ── PydashMergeProcessor ───────────────────────────────────────────


class PydashMergeProcessor(BaseProcessor):
    """Deep merge defaults в body (template-style enrichment).

    Args:
        defaults: dict для deep merge. Recursive — existing keys
            в body сохраняются, missing keys заполняются из defaults.
        overwrite: если False (default) — existing values в body НЕ
            перезаписываются defaults. Если True — defaults overwrite.
        name: имя процессора.

    Example::

        PydashMergeProcessor(defaults={
            "audit": {"source": "api_v2", "version": 1},
            "metadata": {"retries": 0},
        })
        # body = {"audit": {"version": 2}} →
        # body = {"audit": {"version": 2, "source": "api_v2"}, "metadata": {"retries": 0}}
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        defaults: dict[str, Any],
        *,
        overwrite: bool = False,
        name: str | None = None,
    ) -> None:
        if not isinstance(defaults, dict):
            raise ValueError("PydashMergeProcessor: defaults must be a dict")
        super().__init__(name=name or "pydash_merge")
        self._defaults = copy.deepcopy(defaults)
        self._overwrite = overwrite

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, dict):
            new_body = copy.deepcopy(self._defaults)
        elif self._overwrite:
            new_body = pydash.objects.merge(
                copy.deepcopy(body), copy.deepcopy(self._defaults)
            )
        else:
            # body wins over defaults (defaults заполняют только отсутствующие ключи).
            new_body = pydash.objects.merge(
                copy.deepcopy(self._defaults), copy.deepcopy(body)
            )
        exchange.set_out(body=new_body, headers=dict(exchange.in_message.headers))
        _log.debug("PydashMerge: applied defaults (overwrite=%s)", self._overwrite)

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "pydash_merge", "overwrite": self._overwrite}
