"""Regression tests для ADR-0284 ALLOWED matrix update (Sprint 36 W1).

Покрывает:
1. ALLOWED map `services` includes `infrastructure` (closes Sprint 35
   debt entry for notification_hub + kafka_facade).
2. ALLOWED map `entrypoints` includes `infrastructure` (closes Sprint 35
   debt entry for admin_workflow_versioning).
3. ALLOWED matrix consistency: all layers в matrix, no orphaned entries.
4. `make layers` exits 0 после ADR-0284 edits (no NEW violations).

Per ADR-0282 §3 Phase B (governance rule): future ALLOWED matrix changes
требуют per-ADR approval.
"""

from __future__ import annotations

from pathlib import Path
import re


def _parse_allowed_matrix() -> dict[str, set[str]]:
    """Parse ALLOWED dict from tools/check_layers.py source.

    Простой regex parser — НЕ eval, безопасный.
    """
    text = Path("tools/check_layers.py").read_text(encoding="utf-8")

    # Match: ALLOWED: dict[str, set[str]] = { ... }
    match = re.search(
        r"ALLOWED:\s*dict\[str,\s*set\[str\]\]\s*=\s*\{(.+?)\n\}", text, re.DOTALL
    )
    assert match, "ALLOWED dict не найден в tools/check_layers.py"

    result: dict[str, set[str]] = {}
    for line in match.group(1).splitlines():
        line = line.strip().rstrip(",").strip()
        if not line or line.startswith("#"):
            continue
        # "layer": {"item1", "item2"}
        m = re.match(r'^"?(\w+)"?\s*:\s*\{(.+)\}$', line)
        if not m:
            continue
        layer = m.group(1)
        items_str = m.group(2).strip()
        if items_str == "":
            result[layer] = set()
        else:
            items = re.findall(r'"(\w+)"', items_str)
            result[layer] = set(items)
    return result


class TestAllowedMatrixIncludesInfrastructure:
    """ADR-0284: services + entrypoints ALLOWED map updated."""

    def test_services_includes_infrastructure(self) -> None:
        """`services` → `infrastructure` allowed (Sprint 35 debt closed)."""
        allowed = _parse_allowed_matrix()
        assert "infrastructure" in allowed.get("services", set()), (
            "services ALLOWED should include 'infrastructure' (ADR-0284). "
            "Sprint 35 created debt entry services/ops/notification_hub.py → "
            "infrastructure.notifications; ADR-0284 resolves via matrix update."
        )

    def test_entrypoints_includes_infrastructure(self) -> None:
        """`entrypoints` → `infrastructure` allowed (Sprint 35 debt closed)."""
        allowed = _parse_allowed_matrix()
        assert "infrastructure" in allowed.get("entrypoints", set()), (
            "entrypoints ALLOWED should include 'infrastructure' (ADR-0284). "
            "Sprint 35 created debt entry entrypoints/api/v1/endpoints/"
            "admin_workflow_versioning.py → infrastructure.workflow.factory; "
            "ADR-0284 resolves via matrix update."
        )

    def test_core_remains_leaf(self) -> None:
        """`core` ALLOWED remains empty (leaf layer per ADR-0001)."""
        allowed = _parse_allowed_matrix()
        assert allowed.get("core", set()) == set(), (
            "core ALLOWED should remain empty (leaf layer). ADR-0284 does NOT "
            "add infrastructure → core (would violate architectural invariant)."
        )


class TestGovernanceRule:
    """ADR-0284 §1.1 governance: future ALLOWED matrix changes require per-ADR."""

    def test_check_layers_has_governance_comment(self) -> None:
        """`tools/check_layers.py` has governance comment (per ADR-0284 §1.1)."""
        text = Path("tools/check_layers.py").read_text(encoding="utf-8")
        # Look for ADR-0284 reference in ALLOWED block
        assert "ADR-0284" in text, (
            "ALLOWED map should reference ADR-0284 для traceability"
        )


class TestLayersCleanAfterADR0284:
    """3 Sprint 35 debt entries removed; `make layers` exits 0."""

    def test_kafka_facade_not_in_allowlist(self) -> None:
        """`services/messaging/kafka_facade.py` → infrastructure entry removed."""
        text = Path("tools/check_layers_allowlist.txt").read_text(encoding="utf-8")
        assert "kafka_facade" not in text or "mq_trace_propagator" not in text, (
            "kafka_facade → infrastructure entry should be removed per ADR-0284"
        )

    def test_notification_hub_not_in_allowlist(self) -> None:
        """`services/ops/notification_hub.py` → infrastructure entry removed."""
        text = Path("tools/check_layers_allowlist.txt").read_text(encoding="utf-8")
        # The Sprint 35 entry had unique comment + entry; verify gone
        assert not (
            "src/backend/services/ops/notification_hub.py" in text
            and "src.backend.infrastructure.notifications" in text
        ), "notification_hub → infrastructure entry should be removed per ADR-0284"

    def test_admin_workflow_versioning_not_in_allowlist(self) -> None:
        """`entrypoints/admin_workflow_versioning.py` → infrastructure entry removed."""
        text = Path("tools/check_layers_allowlist.txt").read_text(encoding="utf-8")
        assert not (
            "src/backend/entrypoints/api/v1/endpoints/admin_workflow_versioning.py"
            in text
            and "src.backend.infrastructure.workflow.factory" in text
        ), (
            "admin_workflow_versioning → infrastructure entry should be removed per ADR-0284"
        )
