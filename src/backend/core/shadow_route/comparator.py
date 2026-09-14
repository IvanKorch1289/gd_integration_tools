"""Shadow Router / Canary Validation — pure-Python (Wave 4 #51).

Note: differs from ``canary_deploy`` (which is metrics-based traffic
split for gradual rollout). This module is for SHADOW execution:
run both baseline and new version in parallel, compare results, decide
on promotion.
"""

from __future__ import annotations

import enum
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Union

logger = logging.getLogger(__name__)

__all__ = (
    "ComparisonRule",
    "ComparisonType",
    "ShadowComparator",
    "ShadowResult",
    "ShadowRouter",
    "get_shadow_router",
)


RouteFn = Callable[[Any], Union[Any, Awaitable[Any]]]


class ComparisonType(str, enum.Enum):
    """How to compare shadow vs baseline."""

    EXACT = "exact"  # dict equality.
    APPROX_EQUAL = "approx_equal"  # values within tolerance.
    SUBSET = "subset"  # shadow fields ⊆ baseline fields.
    CONTAINS = "contains"  # baseline fields ⊆ shadow fields.
    CUSTOM = "custom"  # user-defined function.


@dataclass(slots=True)
class ShadowResult:
    """Result of shadow execution."""

    route_id: str
    version: str  # "baseline" or "v1.2.3"
    payload: Any = None
    output: Any = None
    duration_ms: float = 0.0
    error: str | None = None
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "version": self.version,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "timestamp": self.timestamp,
            "has_output": self.output is not None,
        }


@dataclass(slots=True)
class ComparisonRule:
    """Rule для shadow vs baseline comparison.

    Attributes:
        type: ComparisonType.
        tolerance: Absolute tolerance для APPROX_EQUAL.
        required_fields: Fields that MUST be present in both (для SUBSET/CONTAINS).
        custom_fn: Callable (baseline, shadow) -> bool для CUSTOM.
        description: Human-readable description.
    """

    type: ComparisonType = ComparisonType.EXACT
    tolerance: float = 0.0
    required_fields: tuple[str, ...] = ()
    custom_fn: Callable[[Any, Any], bool] | None = None
    description: str = ""


class ShadowComparator:
    """Compares two ShadowResult objects."""

    def compare(
        self,
        baseline: ShadowResult,
        shadow: ShadowResult,
        rule: ComparisonRule,
    ) -> "ComparisonOutcome":
        """Compare baseline vs shadow using rule."""
        if baseline.error or shadow.error:
            return ComparisonOutcome(
                passed=False,
                reason=(
                    f"error in execution: "
                    f"baseline={baseline.error}, shadow={shadow.error}"
                ),
                diff=_diff_summary(baseline, shadow),
            )

        ok, reason = self._apply_rule(baseline.output, shadow.output, rule)
        return ComparisonOutcome(
            passed=ok,
            reason=reason,
            diff=_diff_summary(baseline, shadow) if not ok else None,
        )

    def _apply_rule(
        self,
        baseline: Any,
        shadow: Any,
        rule: ComparisonRule,
    ) -> tuple[bool, str]:
        if rule.type == ComparisonType.EXACT:
            if baseline == shadow:
                return True, "exact match"
            return False, f"outputs differ: baseline={baseline!r}, shadow={shadow!r}"
        if rule.type == ComparisonType.APPROX_EQUAL:
            return _approx_equal(baseline, shadow, rule.tolerance)
        if rule.type == ComparisonType.SUBSET:
            missing = set(rule.required_fields) - set(_flatten(shadow).keys())
            if missing:
                return False, f"shadow missing fields: {missing}"
            return True, "all required fields present in shadow"
        if rule.type == ComparisonType.CONTAINS:
            missing = set(rule.required_fields) - set(_flatten(baseline).keys())
            if missing:
                return False, f"baseline missing fields: {missing}"
            return True, "all required fields present in baseline"
        if rule.type == ComparisonType.CUSTOM:
            if rule.custom_fn is None:
                return False, "CUSTOM rule requires custom_fn"
            ok = rule.custom_fn(baseline, shadow)
            return ok, ("custom passed" if ok else "custom returned False")
        return False, f"unknown rule type: {rule.type}"


@dataclass(slots=True)
class ComparisonOutcome:
    """Result of comparison."""

    passed: bool
    reason: str = ""
    diff: dict[str, Any] | None = None


class ShadowRouter:
    """Routes + shadow functions + comparator.

    Maintains registry of route versions, allows running shadow + baseline
    in parallel and comparing results.
    """

    def __init__(self) -> None:
        self._baseline: dict[tuple[str, str], RouteFn] = {}
        self._shadow: dict[tuple[str, str], RouteFn] = {}
        self._comparator = ShadowComparator()
        self._mirror_pct: dict[str, float] = {}

    # ─── Registration ──────────────────────────────────

    def add_baseline(
        self, route_id: str, version: str, fn: RouteFn
    ) -> None:
        """Register baseline function для route."""
        self._baseline[(route_id, version)] = fn

    def add_shadow(
        self, route_id: str, version: str, fn: RouteFn
    ) -> None:
        """Register shadow function (new version) для route."""
        self._shadow[(route_id, version)] = fn

    def set_mirror_percent(self, route_id: str, percent: float) -> None:
        """Set % of requests that should be mirrored to shadow."""
        self._mirror_pct[route_id] = percent

    def get_mirror_percent(self, route_id: str) -> float:
        return self._mirror_pct.get(route_id, 0.0)

    # ─── Mirror decision (sticky by tenant) ───────────

    def should_mirror(
        self, route_id: str, tenant_id: str | None = None
    ) -> bool:
        """Determine if a request should be mirrored to shadow.

        Sticky by MD5(tenant_id) for consistent UX.
        """
        percent = self.get_mirror_percent(route_id)
        if percent <= 0:
            return False
        if percent >= 100:
            return True
        if tenant_id is None:
            import random

            # S311: random для traffic-split (не crypto) — canary bucket.
            return random.random() * 100 < percent  # noqa: S311
        # Sticky by hash.
        hash_val = int(
            hashlib.md5(tenant_id.encode("utf-8")).hexdigest(), 16  # noqa: S324
        )
        bucket = (hash_val % 10000) / 100.0
        return bucket < percent

    # ─── Execution ─────────────────────────────────────

    async def run_shadow(
        self,
        route_id: str,
        shadow_version: str,
        payload: Any,
    ) -> ShadowResult:
        """Run shadow version и record result."""
        import inspect
        import time

        fn = self._shadow.get((route_id, shadow_version))
        if fn is None:
            return ShadowResult(
                route_id=route_id,
                version=shadow_version,
                payload=payload,
                error=f"shadow version '{shadow_version}' not registered",
            )
        start = time.time()
        try:
            output = fn(payload)
            if inspect.iscoroutine(output):
                output = await output
            return ShadowResult(
                route_id=route_id,
                version=shadow_version,
                payload=payload,
                output=output,
                duration_ms=(time.time() - start) * 1000,
                timestamp=time.time(),
            )
        except Exception as exc:
            return ShadowResult(
                route_id=route_id,
                version=shadow_version,
                payload=payload,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.time() - start) * 1000,
                timestamp=time.time(),
            )

    async def run_baseline(
        self,
        route_id: str,
        baseline_version: str,
        payload: Any,
    ) -> ShadowResult:
        """Run baseline version."""
        import inspect
        import time

        fn = self._baseline.get((route_id, baseline_version))
        if fn is None:
            return ShadowResult(
                route_id=route_id,
                version=baseline_version,
                payload=payload,
                error=f"baseline version '{baseline_version}' not registered",
            )
        start = time.time()
        try:
            output = fn(payload)
            if inspect.iscoroutine(output):
                output = await output
            return ShadowResult(
                route_id=route_id,
                version=baseline_version,
                payload=payload,
                output=output,
                duration_ms=(time.time() - start) * 1000,
                timestamp=time.time(),
            )
        except Exception as exc:
            return ShadowResult(
                route_id=route_id,
                version=baseline_version,
                payload=payload,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.time() - start) * 1000,
                timestamp=time.time(),
            )

    def compare(
        self,
        baseline: ShadowResult,
        shadow: ShadowResult,
        rule: ComparisonRule,
    ) -> ComparisonOutcome:
        """Compare baseline vs shadow using rule."""
        return self._comparator.compare(baseline, shadow, rule)


# ─── Helpers ─────────────────────────────────────────


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten dict (1 level) for SUBSET/CONTAINS comparison."""
    if not isinstance(obj, dict):
        return {prefix: obj} if prefix else {"value": obj}
    result: dict[str, Any] = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        result[key] = v
    return result


def _approx_equal(
    a: Any, b: Any, tolerance: float
) -> tuple[bool, str]:
    """Compare numbers (or dicts of numbers) with absolute tolerance."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if abs(a - b) <= tolerance:
            return True, f"{a} ≈ {b} (tolerance {tolerance})"
        return False, f"{a} != {b} (tolerance {tolerance})"
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False, f"keys differ: {set(a.keys()) ^ set(b.keys())}"
        for k in a:
            ok, reason = _approx_equal(a[k], b[k], tolerance)
            if not ok:
                return False, f"field {k}: {reason}"
        return True, "all fields approx equal"
    if a == b:
        return True, "exact match"
    return False, f"types differ: {type(a).__name__} vs {type(b).__name__}"


def _diff_summary(
    baseline: ShadowResult, shadow: ShadowResult
) -> dict[str, Any]:
    """Quick diff summary для failing comparison."""
    return {
        "route_id": baseline.route_id,
        "baseline_version": baseline.version,
        "shadow_version": shadow.version,
        "baseline_output": repr(baseline.output)[:200],
        "shadow_output": repr(shadow.output)[:200],
    }


# Singleton.
_router: ShadowRouter | None = None


def get_shadow_router() -> ShadowRouter:
    global _router
    if _router is None:
        _router = ShadowRouter()
    return _router


def reset_shadow_router() -> None:
    global _router
    _router = None
