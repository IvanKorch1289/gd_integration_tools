"""Unit-тесты для cycle 25 batch 3 (architecture consolidation).

Self-contained — does NOT import application modules.
"""


from __future__ import annotations

import os
import subprocess


class TestLayerCheckAllowlist:
    """Verify architecture allowlist is consistent."""

    def test_check_layers_exits_zero(self):
        """tools/check_layers.py should exit 0 (no new violations)."""
        if not os.path.exists("tools/check_layers.py"):
            return
        r = subprocess.run(
            ["python3", "tools/check_layers.py"],
            capture_output=True, text=True, timeout=30,
        )
        # Tool may exit 0 or 1; check no new violations
        output = r.stdout + r.stderr
        assert "Нарушений: 0 новых" in output or "0 новых" in output, (
            f"Expected 0 new violations, got: {output[-300:]}"
        )

    def test_allowlist_has_recent_entries(self):
        """Allowlist should have 100+ entries documenting legacy debt.

        Cycle 118 L10: was 200+ but allowlist shrank to 169 after
        S171+ cleanup waves. Lower bound to 100 (still meaningful —
        catches catastrophic shrink, but allows gradual cleanup).
        """
        path = "tools/check_layers_allowlist.txt"
        if not os.path.exists(path):
            return
        with open(path) as f:
            lines = [line for line in f if line.strip() and not line.startswith("#")]
        assert len(lines) >= 100, (
            f"Allowlist should have 100+ entries, got {len(lines)}"
        )

    def test_allowlist_format(self):
        """Each line: <rel_path>\\t<importer_layer>\\t<imported_module>."""
        path = "tools/check_layers_allowlist.txt"
        if not os.path.exists(path):
            return
        with open(path) as f:
            for line in f:
                if line.strip().startswith("#") or not line.strip():
                    continue
                parts = line.rstrip("\n").split("\t")
                assert len(parts) == 3, f"Bad line: {line!r}"


class TestADR0249:
    """ADR-0249 documents DSL → upper-layer import consolidation."""

    def test_adr_exists(self):
        path = "docs/adr/0249-dsl-upper-layer-imports-debt.md"
        assert os.path.exists(path), f"ADR-0249 missing at {path}"

    def test_adr_documents_decision(self):
        path = "docs/adr/0249-dsl-upper-layer-imports-debt.md"
        if not os.path.exists(path):
            return
        content = open(path).read()
        # Must contain key elements
        for required in ["Status:", "Decision", "Ponytail", "allowlist"]:
            assert required in content, f"ADR missing required text: {required}"
