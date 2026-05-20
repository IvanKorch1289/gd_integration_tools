"""Unit-тесты для DSL route renderer (S10 K3 W9)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[3] / "tools" / "dsl_render.py"
    spec = importlib.util.spec_from_file_location("_dsl_render_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


SAMPLE_ROUTE = {
    "route_id": "sample",
    "source": "http:GET /x",
    "steps": [
        {"call_function": {"ref": "m:f"}},
        {"http_call": {"url": "https://api/y"}},
    ],
    "to": {"response": {"code": 200}},
}


def test_render_mermaid_contains_flowchart_header() -> None:
    out = mod.render_mermaid(SAMPLE_ROUTE)
    assert out.startswith("flowchart TD")
    assert "Source:" in out
    assert "call_function" in out
    assert "http_call" in out


def test_render_mermaid_arrows_connect_steps() -> None:
    out = mod.render_mermaid(SAMPLE_ROUTE)
    assert " --> " in out
    # source → first step → ... → end
    arrows = [ln for ln in out.splitlines() if "-->" in ln]
    assert len(arrows) >= 3


def test_render_bpmn_xml_structure() -> None:
    out = mod.render_bpmn(SAMPLE_ROUTE)
    assert out.startswith('<?xml version="1.0"')
    assert "bpmn:process" in out
    assert "StartEvent_1" in out
    assert "EndEvent_1" in out


def test_render_dispatch_via_render_fn() -> None:
    m = mod.render(SAMPLE_ROUTE, "mermaid")
    b = mod.render(SAMPLE_ROUTE, "bpmn")
    s = mod.render(SAMPLE_ROUTE, "svg")
    assert m.startswith("flowchart")
    assert b.startswith("<?xml")
    assert "graphviz" in s


def test_render_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="Unknown format"):
        mod.render(SAMPLE_ROUTE, "doc")


def test_empty_steps_route_renders_minimal() -> None:
    out = mod.render_mermaid({"route_id": "empty", "source": "http:GET /"})
    # Должен быть хотя бы start node.
    assert "Source:" in out


def test_slug_filters_unsafe_chars() -> None:
    assert mod._slug("hello world!") == "hello_world_"
    assert mod._slug("") == "n"
    assert len(mod._slug("a" * 100)) == 32
