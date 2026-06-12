"""S77 W3 — Per-tenant override с specificity-based resolution (P0-C).

FINAL_REPORT_V2 P0-C improvement: current :meth:`PolicyResolver.resolve`
использует "first match wins" (порядок roots). Это означает что
specific policy (e.g. ``tenant_pattern="premium*"``) может быть
override'нут общей (``tenant_pattern="*"``) если общая в roots первая.

S77 W3: :meth:`PolicyResolver.resolve_specific` — выбирает MOST
specific match по specificity score.

**Specificity** (higher = more specific):
* ``tenant_pattern="*"` → score 0
* ``tenant_pattern="premium*"` → score 1 (length)
* ``tenant_pattern="premium_us*"` → score 2 (length)
* ``tenant_pattern="premium_user"`` → score 3 (exact, longest)

Plus: ties resolved by workflow_pattern specificity (same logic).

**Backward-compat**:
* ``resolve()`` unchanged (first match wins) — pre-S77 callers
  unaffected.
* ``resolve_specific()`` NEW — opt-in для callers которым важна
  precedence (multi-tenant deployments).

**Use case** (FINAL_REPORT_V2 P0-C):
```python
# Global policy (all tenants)
- workflow_pattern: "credit_check"
  tenant_pattern: "*"
  budget:
    max_cost_usd: 0.50

# Premium override (specific tenant)
- workflow_pattern: "credit_check"
  tenant_pattern: "premium_*"
  budget:
    max_cost_usd: 2.00  # higher limit для premium
```

С ``resolve()`` — order matters, может быть wrong.
С ``resolve_specific()`` — premium_* всегда побеждает (more specific).
"""

from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec

_logger = get_logger("core.ai.policy.resolver.specific")

__all__ = ("compute_specificity",)


def compute_specificity(pattern: str, value: str) -> int:
    """Compute specificity score для pattern matching value.

    Higher score = more specific match.

    Algorithm:
    * Exact match: score = len(pattern)
    * Wildcard pattern: score = (len of non-wildcard prefix) + 0
      (no bonus за trailing wildcard)
    * No match: score = -1

    Examples:
        compute_specificity("*", "any_value") = 0
        compute_specificity("premium_*", "premium_user") = 8 (len "premium_")
        compute_specificity("premium_user", "premium_user") = 12 (exact)
        compute_specificity("premium_*", "basic_user") = -1 (no match)

    Args:
        pattern: glob pattern (e.g. ``"premium_*"``, ``"*"``).
        value: concrete value to match against.

    Returns:
        Specificity score (int, -1 if no match).
    """
    if not fnmatch.fnmatchcase(value, pattern):
        return -1  # No match

    if pattern == value:
        # Exact match — most specific
        return len(pattern)

    # Wildcard match — score по longest non-wildcard prefix
    # Find longest prefix before any wildcard char (*, ?, [...])
    wildcard_idx = len(pattern)
    for i, ch in enumerate(pattern):
        if ch in "*?[":
            wildcard_idx = i
            break
    return wildcard_idx


def find_specific_match(
    policies: "list[AIPolicySpec]",
    workflow_id: str,
    tenant_id: str,
) -> "AIPolicySpec | None":
    """Find MOST specific match in policy list.

    Compares all policies (workflow_pattern + tenant_pattern match),
    returns highest-specificity. Ties broken by:
    1. tenant_pattern specificity (more specific wins)
    2. workflow_pattern specificity (more specific wins)
    3. list order (first wins — stable for equal-specificity)

    Args:
        policies: list of loaded AIPolicySpec.
        workflow_id: concrete workflow_id.
        tenant_id: concrete tenant_id.

    Returns:
        Most specific :class:`AIPolicySpec` or ``None`` if no match.
    """
    best: tuple[int, int, int, AIPolicySpec] | None = None
    for idx, policy in enumerate(policies):
        wf_score = compute_specificity(policy.workflow_pattern, workflow_id)
        if wf_score < 0:
            continue
        tn_score = compute_specificity(policy.tenant_pattern, tenant_id)
        if tn_score < 0:
            continue
        # -idx для стабильности (earlier index = higher priority при tie)
        key = (tn_score, wf_score, -idx, policy)
        if best is None or key > best:
            best = key

    return best[3] if best is not None else None
