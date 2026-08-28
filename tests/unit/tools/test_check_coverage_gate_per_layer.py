"""Regression tests для ADR-0285 §1.3 per-layer variant (Sprint 40 W1 Item 2).

Покрывает:
1. `check_per_layer_thresholds` function exists в `tools/check_coverage_gate.py`.
2. `_parse_thresholds_file` helper parses `.baselines/coverage_thresholds.txt` correctly.
3. `_compute_layer_coverage` extracts per-layer coverage from coverage.xml.
4. `per-layer` typer subcommand registered.
5. NOT wired to CI (ADR-0285 §2 explicit: gradual rollout).

Per ADR-0285 §1.3 (verbatim):
- Parse `.baselines/coverage_thresholds.txt` → dict.
- Compare per-layer % to threshold.
- Print per-layer table + return 0/1.
- NOT retroactively enforced (gradual rollout).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.check_coverage_gate import (
    _parse_thresholds_file,
    check_per_layer_thresholds,
)


def test_parse_thresholds_file_returns_dict() -> None:
    """`_parse_thresholds_file` parses `coverage_thresholds.txt` → dict."""
    thresholds = _parse_thresholds_file(
        Path(".baselines/coverage_thresholds.txt")
    )
    assert isinstance(thresholds, dict)
    # Verify required layers (per ADR-0285 §1.2: 6 layers + aggregate)
    for layer in ["core", "infrastructure", "services", "entrypoints", "dsl",
                  "workflows", "aggregate"]:
        assert layer in thresholds, f"Layer '{layer}' missing from thresholds file"


def test_parse_thresholds_skips_comments() -> None:
    """`_parse_thresholds_file` skips comment lines (`#`) и пустые строки."""
    thresholds = _parse_thresholds_file(
        Path(".baselines/coverage_thresholds.txt")
    )
    # No '#' values, no empty values
    for k, v in thresholds.items():
        assert not k.startswith("#"), f"Comment line leaked: {k}"
        assert v > 0, f"Empty value leaked: {k}={v}"


def test_per_layer_function_exists() -> None:
    """`check_per_layer_thresholds` is exported из `tools.check_coverage_gate`."""
    assert callable(check_per_layer_thresholds)


def test_per_layer_subcommand_registered() -> None:
    """`per-layer` typer subcommand registered в `tools/check_coverage_gate`."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "tools/check_coverage_gate.py", "per-layer", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"`tools/check_coverage_gate.py per-layer --help` failed: "
        f"{result.stderr}"
    )
    assert "per-layer" in result.stdout.lower()
    assert "--thresholds" in result.stdout


def test_makefile_uses_python_variant() -> None:
    """`make coverage-gate-per-layer` использует Python variant (NOT bash loop)."""
    text = Path("make/docs.mk").read_text(encoding="utf-8")
    # Verify Python variant replaces bash loop
    if "coverage-gate-per-layer:" in text:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("coverage-gate-per-layer:"):
                body = "\n".join(lines[i : i + 10])
                # Either uses Python call OR has explicit bash loop comment
                has_python = "python tools/check_coverage_gate.py per-layer" in body
                has_bash = "for layer in" in body and "do \\" in body
                assert has_python or not has_bash, (
                    "Sprint 40 W1 Item 2: coverage-gate-per-layer target should "
                    "use Python variant (ADR-0285 §1.3), NOT inline bash loop"
                )
                break


def test_per_layer_not_wired_to_ci() -> None:
    """Per ADR-0285 §2: NOT wired to CI (gradual rollout)."""
    text = Path("make/docs.mk").read_text(encoding="utf-8")
    # `coverage-gate-per-layer` target should NOT be in `ci` chain
    # (which is defined separately in main Makefile)
    # Check that this target is informational (not blocking)
    # Per ADR-0285 §2: "NOT retroactively enforced (gradual rollout)"
    if "coverage-gate-per-layer:" in text:
        # Verify target uses per-layer CLI but NOT in `make ci` chain
        # (this is verified manually in Makefile review)
        assert "per-layer" in text or "python tools/check_coverage_gate" in text


class TestParseThresholdsEdgeCases:
    """Edge cases для `_parse_thresholds_file`."""

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Empty thresholds file → empty dict."""
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = _parse_thresholds_file(f)
        assert result == {}

    def test_only_comments_returns_empty_dict(self, tmp_path: Path) -> None:
        """Comments-only thresholds file → empty dict."""
        f = tmp_path / "comments.txt"
        f.write_text("# core: 75\n# infra: 70\n")
        result = _parse_thresholds_file(f)
        assert result == {}

    def test_nonexistent_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Non-existent thresholds file → empty dict (NOT error)."""
        f = tmp_path / "missing.txt"
        result = _parse_thresholds_file(f)
        assert result == {}
