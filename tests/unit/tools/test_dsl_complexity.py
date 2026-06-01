"""Unit-тесты для DSL complexity gate (S10 K3 W2)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = (
        Path(__file__).resolve().parents[3]
        / "tools"
        / "checks"
        / "dsl_complexity.py"
    )
    spec = importlib.util.spec_from_file_location("_dsl_complexity_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_simple_route_low_complexity() -> None:
    yaml_text = """
route_id: simple
source: { http: { method: GET, path: /x } }
steps:
  - call_function: { ref: m:f }
  - to: { response: { code: 200 } }
"""
    r = mod.analyze_yaml(yaml_text, "simple.yaml")
    assert r.ok
    assert r.cyclomatic == 1  # 1 + 0 decision points
    assert r.nesting == 0


def test_choice_branch_increments_cyclomatic() -> None:
    yaml_text = """
route_id: with_choice
source: { http: {} }
steps:
  - choice:
      when:
        - condition: a
          steps: []
        - condition: b
          steps: []
        - condition: c
          steps: []
      otherwise:
        steps: []
"""
    r = mod.analyze_yaml(yaml_text, "choice.yaml")
    # 1 (choice itself) + 2 (extra cases) = 3, +1 base = 4
    assert r.cyclomatic >= 4
    assert r.nesting >= 1


def test_too_many_steps_violates_budget() -> None:
    yaml_text = "route_id: x\nsource: {}\nsteps:\n" + "\n".join(
        f"  - call_function: {{ ref: m:f{i} }}" for i in range(51)
    )
    r = mod.analyze_yaml(yaml_text, "many.yaml", max_steps=50)
    assert not r.ok
    assert any("steps=51" in v for v in r.violations)


def test_deep_nesting_violates() -> None:
    yaml_text = """
route_id: deep
source: {}
steps:
  - choice:
      when:
        - condition: a
          steps:
            - choice:
                when:
                  - condition: b
                    steps:
                      - choice:
                          when:
                            - condition: c
                              steps:
                                - choice:
                                    when:
                                      - condition: d
                                        steps:
                                          - choice:
                                              when:
                                                - condition: e
                                                  steps: []
"""
    r = mod.analyze_yaml(yaml_text, "deep.yaml", max_nesting=5)
    assert r.nesting > 5
    assert any("nesting" in v for v in r.violations)


def test_yaml_syntax_error_returns_violation() -> None:
    # Использован незакрытый flow-tag — гарантированно YAMLError.
    r = mod.analyze_yaml("key: [1, 2, 3", "bad.yaml")
    assert not r.ok
    assert any("yaml-syntax" in v for v in r.violations)


def test_thresholds_constants() -> None:
    assert mod.MAX_CYCLOMATIC == 50
    assert mod.MAX_NESTING == 5
    assert mod.MAX_STEPS == 50
