"""Data Quality auto-remediation strategies (Sprint 53 W2).

Extension для ``services/ops/data_quality.py``. Каждый remediator — чистая функция
``(value, params) -> value``. Composable через ``CompositeRemediator``.

Стратегии:
* ``NullDefaultRemediator`` — заменяет None / empty на default
* ``RangeClipRemediator`` — клиппит numeric к [min, max]
* ``RegexMaskRemediator`` — заменяет non-matching strings на mask
* ``EnumFallbackRemediator`` — заменяет invalid enum на fallback
* ``TypeCoerceRemediator`` — конвертирует к expected type
* ``CompositeRemediator`` — цепочка strategies (применяются в порядке)

Usage::

    from src.backend.services.ops.dq_remediation import (
        NullDefaultRemediator,
        RangeClipRemediator,
        CompositeRemediator,
    )

    rem = CompositeRemediator([
        NullDefaultRemediator(default=0),
        RangeClipRemediator(min=0, max=100),
    ])
    fixed = rem.remediate(-5, {})  # → 0 (null default), then clip to [0,100] → 0

Design:
* Pure functions, no I/O, no state.
* Returns original value if no remediation applies (idempotent).
* Logs WARNING on each remediation для observability.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = (
    "CompositeRemediator",
    "EnumFallbackRemediator",
    "NullDefaultRemediator",
    "RangeClipRemediator",
    "RegexMaskRemediator",
    "Remediator",
    "TypeCoerceRemediator",
    "build_remediator",
)

_log = get_logger(__name__)


class Remediator(ABC):
    """Base interface для всех remediation strategies."""

    name: str = "base"

    @abstractmethod
    def remediate(self, value: Any, params: dict[str, Any]) -> Any:
        """Apply remediation. Returns remediated value (or original if N/A)."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


# ── Null / Empty replacement ──────────────────────────────────────────


class NullDefaultRemediator(Remediator):
    """Replace ``None`` / empty-string / empty-collection с ``params['default']``."""

    name = "null_default"

    def __init__(self, default: Any = None) -> None:
        self.default = default

    def remediate(self, value: Any, params: dict[str, Any]) -> Any:
        default = params.get("default", self.default)
        if value is None or value == "" or value == [] or value == {}:
            _log.debug("DQ remediator: replacing null/empty %r → %r", value, default)
            return default
        return value


# ── Numeric range clipping ────────────────────────────────────────────


class RangeClipRemediator(Remediator):
    """Clip numeric value в [min, max] range.

    Non-numeric values: passed through unchanged.
    """

    name = "range_clip"

    def __init__(self, min: float | None = None, max: float | None = None) -> None:
        self.min = min
        self.max = max

    def remediate(self, value: Any, params: dict[str, Any]) -> Any:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return value
        lo = params.get("min", self.min)
        hi = params.get("max", self.max)
        if lo is not None and value < lo:
            _log.debug("DQ remediator: clipping %r below min=%s → %s", value, lo, lo)
            return lo
        if hi is not None and value > hi:
            _log.debug("DQ remediator: clipping %r above max=%s → %s", value, hi, hi)
            return hi
        return value


# ── Regex mask for non-matching strings ───────────────────────────────


class RegexMaskRemediator(Remediator):
    """Replace strings not matching ``params['pattern']`` с ``params['mask']``.

    Default mask: ``"***"``. Empty strings treated as non-matching unless
    ``allow_empty=True``.
    """

    name = "regex_mask"

    def __init__(self, mask: str = "***") -> None:
        self.mask = mask

    def remediate(self, value: Any, params: dict[str, Any]) -> Any:
        if not isinstance(value, str):
            return value
        pattern = params.get("pattern")
        if not pattern:
            return value
        try:
            match = re.match(pattern, value)
        except re.error as e:
            _log.warning("DQ remediator: invalid regex %r: %s", pattern, e)
            return value
        if not match or (not match.group() and not params.get("allow_empty", False)):
            mask = params.get("mask", self.mask)
            _log.debug("DQ remediator: masking non-matching %r → %r", value, mask)
            return mask
        return value


# ── Enum fallback ────────────────────────────────────────────────────


class EnumFallbackRemediator(Remediator):
    """Replace values not in ``params['allowed']`` с ``params['fallback']``."""

    name = "enum_fallback"

    def __init__(self, fallback: Any = None) -> None:
        self.fallback = fallback

    def remediate(self, value: Any, params: dict[str, Any]) -> Any:
        allowed = params.get("allowed", [])
        if not allowed or value in allowed:
            return value
        fallback = params.get("fallback", self.fallback)
        _log.debug(
            "DQ remediator: replacing invalid enum %r (allowed=%r) → %r",
            value,
            allowed,
            fallback,
        )
        return fallback


# ── Type coercion ────────────────────────────────────────────────────


class TypeCoerceRemediator(Remediator):
    """Convert value в ``params['target_type']`` (int/float/str/bool).

    Возможные targets: ``int``, ``float``, ``str``, ``bool``.
    Falls back to original value on conversion failure.
    """

    name = "type_coerce"

    _CONVERTERS: dict[str, Callable[[Any], Any]] = {
        "int": int,
        "float": float,
        "str": str,
        "bool": lambda v: (
            v
            if isinstance(v, bool)
            else bool(v)
            if isinstance(v, (int, float, str))
            else v
        ),
    }

    def remediate(self, value: Any, params: dict[str, Any]) -> Any:
        target = params.get("target_type")
        if not target:
            return value
        converter = self._CONVERTERS.get(target)
        if converter is None:
            _log.warning("DQ remediator: unknown target_type %r", target)
            return value
        if isinstance(
            value,
            {"int": int, "float": float, "str": str, "bool": bool}.get(
                target, type(value)
            ),
        ):
            return value
        try:
            return converter(value)
        except (ValueError, TypeError) as e:
            _log.debug("DQ remediator: failed to coerce %r → %s: %s", value, target, e)
            return value


# ── Composite ───────────────────────────────────────────────────────


class CompositeRemediator(Remediator):
    """Chain of remediators. Применяются в порядке, каждый видит output предыдущего.

    Stop on first remediation (если ``stop_on_fix=True``, default).
    """

    name = "composite"

    def __init__(self, remediators: list[Remediator], stop_on_fix: bool = True) -> None:
        if not remediators:
            raise ValueError("CompositeRemediator requires at least one child")
        self.remediators = remediators
        self.stop_on_fix = stop_on_fix

    def remediate(self, value: Any, params: dict[str, Any]) -> Any:
        current = value
        for rem in self.remediators:
            before = current
            current = rem.remediate(current, params)
            if self.stop_on_fix and current != before:
                return current
        return current


# ── Factory ──────────────────────────────────────────────────────────


def build_remediator(check: str, params: dict[str, Any]) -> Remediator | None:
    """Build remediator по check type (mirrors DataQualityMonitor check names).

    Returns ``None`` если no remediation applies для этого check type.
    """
    if check == "not_null":
        return NullDefaultRemediator(default=params.get("default", ""))
    if check == "range":
        return RangeClipRemediator(min=params.get("min"), max=params.get("max"))
    if check == "regex":
        return RegexMaskRemediator(mask=params.get("mask", "***"))
    if check == "enum":
        return EnumFallbackRemediator(fallback=params.get("fallback"))
    if check == "type":
        return TypeCoerceRemediator()
    # No remediation для uniqueness, outlier, cardinality, json_schema, length, date_format
    return None
