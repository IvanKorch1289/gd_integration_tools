"""Glom-based EIP processors для declarative data shaping (S57 W4).

Apache Camel EIP / DSL extension: glom-style path access с Coalesce/Spec/Auto.
Uses :mod:`glom` 25.x (Sprint 5 dep, S57 W4 activation) для declarative
path traversal, type-safe extraction, и multi-fallback chains.

Glom API primer (25.x):
* ``glom(obj, "a.b.c", default=None)`` — dotted path access.
* ``glom(obj, Path("a", "b", "c"))`` — programmatic path.
* ``glom(obj, Coalesce("a.b", "x.y", "z"), default="fallback")`` —
  try multiple paths in order; first match wins.
* ``glom(obj, Spec(...))`` — declarative structure with default.
* ``glom(obj, Auto)`` — auto-detect type (list/dict/str → default behavior).

Use cases (DSL pipelines):
* :class:`GlomExtractProcessor` — extract nested value с multi-fallback
  (Coalesce) — ``"customer.email"`` OR ``"user.email"`` OR default.
* :class:`GlomTransformProcessor` — apply Spec() для body reshape
  (declarative output structure).
* :class:`GlomFlattenProcessor` — flatten nested dict в single-level dict
  с dot-keys.

Использование::

    from src.backend.dsl.engine.processors.eip.glom_ops import (
        GlomExtractProcessor,
        GlomTransformProcessor,
    )

    # Multi-fallback extraction
    .process(GlomExtractProcessor(
        paths=["customer.email", "user.email", "contact.email"],
        default="unknown@example.com",
    ))

    # Declarative reshape
    .process(GlomTransformProcessor(
        spec={
            "user_id": "id",
            "name": "profile.full_name",
            "tags": "metadata.tags",
        }
    ))

Thread-safe: glom pure functions; processor instances immutable post-construction.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from collections.abc import Sequence
from typing import Any, ClassVar

import glom
from glom import Coalesce, Path

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("GlomExtractProcessor", "GlomFlattenProcessor", "GlomTransformProcessor")

_log = get_logger(__name__)


# ── GlomExtractProcessor ────────────────────────────────────────────


class GlomExtractProcessor(BaseProcessor):
    """Extract nested value с multi-fallback chain (glom Coalesce).

    Args:
        paths: ordered list of paths для try (first match wins).
            Может быть dotted strings (``"customer.email"``) или
            :class:`glom.Path` instances для programmatic composition.
        default: fallback value если ВСЕ paths miss.
        write_back: если True — extracted value replaces body.
        property_name: имя property для extracted value
            (default ``glom_extracted``).
        name: имя процессора.

    Example::

        GlomExtractProcessor(
            paths=["customer.email", "user.email", "contact.email"],
            default="anonymous",
        )
        # body = {"customer": {"email": "a@b.com"}} → "a@b.com"
        # body = {"user": {"email": "u@x.com"}} → "u@x.com"
        # body = {} → "anonymous"
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        paths: Sequence[str | Path],
        *,
        default: Any = None,
        write_back: bool = False,
        property_name: str = "glom_extracted",
        name: str | None = None,
    ) -> None:
        if not paths:
            raise ValueError("GlomExtractProcessor: paths must be non-empty")
        super().__init__(name=name or f"glom_extract:{len(paths)}_paths")
        # Strings passed to glom directly support dotted notation ("a.b.c").
        # Path instances are kept as-is (programmatic composition).
        self._paths: list[str | Path] = [
            p if isinstance(p, Path) else str(p) for p in paths
        ]
        self._default = default
        self._write_back = write_back
        self._property_name = property_name

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        # Coalesce: try paths in order, first match wins.
        coalesce = Coalesce(*self._paths, default=self._default)
        value = glom.glom(body, coalesce, default=self._default)
        exchange.set_property(self._property_name, value)
        _log.debug("GlomExtract[%s]: %r", [str(p) for p in self._paths], value)
        if self._write_back:
            exchange.set_out(body=value, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "glom_extract",
            "paths": [str(p) for p in self._paths],
            "write_back": self._write_back,
        }


# ── GlomTransformProcessor ──────────────────────────────────────────


class GlomTransformProcessor(BaseProcessor):
    """Declarative body reshape через :class:`glom.Spec`.

    Args:
        spec: dict mapping output field name → source path (``str``)
            или :class:`glom.Spec` / :class:`glom.Path` для nested extraction.
        default: default value для missing source paths (только при
            ``skip_missing=True``).
        skip_missing: если True (default) — missing sources produce
            output field = default (NOT omitted). Если False — missing
            source keys НЕ appear в output (more compact).
        name: имя процессора.

    Example::

        GlomTransformProcessor(spec={
            "user_id": "id",
            "name": "profile.full_name",
            "tags": "metadata.tags",
        })
        # body = {"id": 1, "profile": {"full_name": "Alice"}, "metadata": {"tags": ["x"]},
        #        "password": "secret"}
        # → {"user_id": 1, "name": "Alice", "tags": ["x"]}
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        spec: dict[str, str | Path],
        *,
        default: Any = None,
        skip_missing: bool = True,
        name: str | None = None,
    ) -> None:
        if not spec:
            raise ValueError("GlomTransformProcessor: spec must be non-empty")
        super().__init__(name=name or f"glom_transform:{len(spec)}_fields")
        # Strings passed to glom directly support dotted notation.
        self._spec: dict[str, str | Path] = {
            k: (v if isinstance(v, Path) else str(v)) for k, v in spec.items()
        }
        self._default = default
        self._skip_missing = skip_missing

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        # Build target dict via per-key glom with default.
        new_body: dict[str, Any] = {}
        for out_key, source_path in self._spec.items():
            try:
                if self._skip_missing:
                    # Pass default — glom returns default для missing paths.
                    value = glom.glom(body, source_path, default=self._default)
                else:
                    # НЕ pass default — glom raises PathAccessError для
                    # missing → skip output key.
                    value = glom.glom(body, source_path)
            except glom.PathAccessError, glom.CheckError, glom.CoalesceError:
                if self._skip_missing:
                    value = self._default
                else:
                    continue
            new_body[out_key] = value
        exchange.set_out(body=new_body, headers=dict(exchange.in_message.headers))
        _log.debug("GlomTransform: %d fields", len(new_body))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "glom_transform",
            "spec": {k: str(v) for k, v in self._spec.items()},
            "skip_missing": self._skip_missing,
        }


# ── GlomFlattenProcessor ────────────────────────────────────────────


class GlomFlattenProcessor(BaseProcessor):
    """Flatten nested dict → single-level dict с dot-keys.

    Args:
        separator: separator для joined keys (default ``"."``).
        max_depth: max recursion depth. ``None`` = unlimited (default).
            ``max_depth=0`` → no recursion (только top-level keys).
            ``max_depth=2`` → recurse 2 levels, остановить на 3-м.
        skip_empty: если True (default) — empty dicts/lists/strings NOT
            included в output.
        name: имя процессора.

    Example::

        GlomFlattenProcessor()
        # body = {"user": {"profile": {"name": "Alice"}}, "id": 1}
        # → {"user.profile.name": "Alice", "id": 1}

        GlomFlattenProcessor(separator="_", max_depth=1)
        # body = {"a": {"b": {"c": 1}}}
        # → {"a": {"b": {"c": 1}}} (max_depth=1: root not recursed)
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        separator: str = ".",
        max_depth: int | None = None,
        skip_empty: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "glom_flatten")
        self._separator = separator
        self._max_depth = max_depth
        self._skip_empty = skip_empty

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, dict):
            _log.warning("GlomFlatten: body is not a dict, no-op")
            return
        flat = _flatten(
            body,
            separator=self._separator,
            max_depth=self._max_depth,
            skip_empty=self._skip_empty,
        )
        exchange.set_out(body=flat, headers=dict(exchange.in_message.headers))
        _log.debug("GlomFlatten: %d flat keys", len(flat))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "glom_flatten",
            "separator": self._separator,
            "max_depth": self._max_depth,
        }


def _flatten(
    obj: Any,
    *,
    separator: str,
    max_depth: int | None,
    skip_empty: bool,
    prefix: str = "",
    current_depth: int = 0,
) -> dict[str, Any]:
    """Recursive flatten dict (and list-of-dicts) to flat dict."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{separator}{k}" if prefix else str(k)
            if isinstance(v, dict) and (max_depth is None or current_depth < max_depth):
                if skip_empty and not v:
                    continue
                nested = _flatten(
                    v,
                    separator=separator,
                    max_depth=max_depth,
                    skip_empty=skip_empty,
                    prefix=key,
                    current_depth=current_depth + 1,
                )
                if nested:
                    out.update(nested)
                elif not skip_empty:
                    out[key] = v
            else:
                if skip_empty and (v is None or v == "" or v == [] or v == {}):
                    continue
                out[key] = v
    return out
