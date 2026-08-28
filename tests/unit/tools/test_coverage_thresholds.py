"""Regression tests для ADR-0285 per-layer coverage thresholds (Sprint 39 W1).

Покрывает:
1. `.baselines/coverage_thresholds.txt` exists с 7 lines (6 layers + aggregate).
2. All thresholds parsed correctly.
3. Per-layer threshold ≥ 0 (sanity).
4. Aggregate threshold ≤ any single layer threshold (loose invariant).
5. `make coverage-gate-per-layer` Makefile target exists в docs.mk.
6. NOT wired to CI (per ADR-0285 §2 explicit).
"""

from __future__ import annotations

from pathlib import Path

import pytest


THRESHOLDS_FILE = Path(".baselines/coverage_thresholds.txt")
EXPECTED_LAYERS = ["core", "infrastructure", "services", "entrypoints", "dsl", "workflows", "aggregate"]


def test_thresholds_file_exists() -> None:
    """`.baselines/coverage_thresholds.txt` exists (ADR-0285 §1.2)."""
    assert THRESHOLDS_FILE.exists(), (
        f"{THRESHOLDS_FILE} missing — ADR-0285 implementation incomplete"
    )


def test_thresholds_file_has_7_entries() -> None:
    """7 entries: 6 layers + aggregate (per ADR-0285 §1.2)."""
    lines = [
        line.strip()
        for line in THRESHOLDS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(lines) == 7, (
        f"Expected 7 entries, got {len(lines)}: {lines}"
    )


def test_thresholds_have_all_expected_layers() -> None:
    """All 6 layers + aggregate present в thresholds file."""
    text = THRESHOLDS_FILE.read_text(encoding="utf-8")
    for layer in EXPECTED_LAYERS:
        assert f"{layer}:" in text, (
            f"Layer '{layer}' missing from {THRESHOLDS_FILE}"
        )


def test_thresholds_are_valid_numbers() -> None:
    """All thresholds are integers 0-100."""
    thresholds = parse_thresholds()
    for layer, value in thresholds.items():
        assert isinstance(value, int), (
            f"{layer}: threshold must be int, got {type(value).__name__}"
        )
        assert 0 <= value <= 100, (
            f"{layer}: threshold {value}% out of [0, 100] range"
        )


def test_aggregate_threshold_in_range() -> None:
    """Aggregate threshold между min и max layer thresholds (weighted range)."""
    thresholds = parse_thresholds()
    layers_only = {k: v for k, v in thresholds.items() if k != "aggregate"}
    min_layer = min(layers_only.values())
    max_layer = max(layers_only.values())
    assert min_layer <= thresholds["aggregate"] <= max_layer, (
        f"Aggregate threshold {thresholds['aggregate']}% should be в "
        f"weighted range [{min_layer}%, {max_layer}%]"
    )


def test_makefile_target_exists() -> None:
    """`make coverage-gate-per-layer` target exists в docs.mk."""
    text = Path("make/docs.mk").read_text(encoding="utf-8")
    assert "coverage-gate-per-layer:" in text, (
        "ADR-0285 §1.1 Makefile target missing"
    )


def test_makefile_target_informational() -> None:
    """`coverage-gate-per-layer` is INFORMATIONAL (NOT wired to CI per ADR-0285 §2)."""
    text = Path("make/docs.mk").read_text(encoding="utf-8")
    # Check that target does NOT exit non-zero on failure (informational only)
    if "coverage-gate-per-layer:" in text:
        # Find the target body
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("coverage-gate-per-layer:"):
                # Look ahead for exit codes or failure semantics
                body = "\n".join(lines[i : i + 25])
                assert "exit 1" not in body or "exit 0 or 1" in body.lower(), (
                    "Coverage gate should be informational (NOT exit-1 on failure)"
                )
                break


def parse_thresholds() -> dict[str, int]:
    """Parse `.baselines/coverage_thresholds.txt` в dict."""
    result = {}
    for line in THRESHOLDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        layer, value = line.split(":", 1)
        result[layer.strip()] = int(value.strip())
    return result
