"""Unit-тесты для Jinja2 macros в DSL YAML (S10 K3 W7)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml as _yaml

from src.backend.dsl.preprocess.jinja_macros import has_jinja_syntax, render_macros


def test_has_jinja_syntax_detects_macros() -> None:
    assert has_jinja_syntax("{% macro x() %}{% endmacro %}")
    assert has_jinja_syntax("hello {{ name }}")
    assert not has_jinja_syntax("route_id: x\nsource: {}")


def test_render_macros_no_op_when_no_jinja_syntax() -> None:
    raw = "route_id: x\nsource: {}\n"
    assert render_macros(raw) == raw


def test_render_macros_expands_variable() -> None:
    raw = "route_id: {{ rid }}\n"
    out = render_macros(raw, context={"rid": "hello"})
    assert "route_id: hello" in out


def test_render_macros_supports_macro_definition() -> None:
    raw = """
{% macro retry(attempts) -%}
attempts: {{ attempts }}
backoff: exponential
{%- endmacro %}
route_id: x
policy:
  {{ retry(5) }}
"""
    out = render_macros(raw)
    assert "attempts: 5" in out
    # raw YAML должен парситься после рендера.
    data = _yaml.safe_load(out)
    assert data["route_id"] == "x"
    assert data["policy"]["attempts"] == 5


def test_render_macros_includes_external_file(tmp_path: Path) -> None:
    inc = tmp_path / "policy.yaml.j2"
    inc.write_text(
        "policy:\n  retry:\n    attempts: 7\n", encoding="utf-8"
    )
    raw = """
route_id: x
{% include 'policy.yaml.j2' %}
"""
    out = render_macros(raw, search_path=tmp_path)
    assert "attempts: 7" in out


def test_strict_undefined_raises_on_typo() -> None:
    raw = "route_id: {{ missin_variable }}\n"
    with pytest.raises(Exception):  # noqa: BLE001
        render_macros(raw, context={"rid": "x"})


def test_render_macros_preserves_indentation() -> None:
    """Jinja-вывод должен оставаться валидным YAML."""
    raw = """
{% macro greet(name) -%}
greeting: hi {{ name }}
{%- endmacro %}
route_id: x
metadata:
  {{ greet('world') }}
"""
    out = render_macros(raw)
    data = _yaml.safe_load(out)
    assert data["metadata"]["greeting"] == "hi world"
