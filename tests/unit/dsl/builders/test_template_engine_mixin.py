"""Unit tests for src.backend.dsl.builders.template_engine_mixin (K3 W3c, S39).

Subagent #2 created template_engine_mixin.py but timed out before test creation.
Orchestrator завершил.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder


@pytest.fixture
def builder() -> RouteBuilder:
    """Fresh RouteBuilder for each test."""
    return RouteBuilder(route_id="test_template", source="internal:test")


class TestTemplateEngine:
    def test_render_template_simple(self, builder: RouteBuilder) -> None:
        result = builder.template_render_str("Hello {{ name }}", {"name": "World"})
        assert result == "Hello World"

    def test_render_template_with_context(self, builder: RouteBuilder) -> None:
        ctx = {"user": {"name": "Alice", "age": 30}, "items": [1, 2, 3]}
        result = builder.template_render_str(
            "{{ user.name }} is {{ user.age }} and has {{ items | length }} items", ctx
        )
        assert result == "Alice is 30 and has 3 items"

    def test_render_template_with_custom_filter(self, builder: RouteBuilder) -> None:
        builder.register_filter("shout", lambda x: str(x).upper() + "!")
        result = builder.template_render_str("{{ 'hello' | shout }}")
        assert result == "HELLO!"

    def test_render_template_default_filter(self, builder: RouteBuilder) -> None:
        # Jinja built-in filter `upper`
        result = builder.template_render_str("{{ 'hello' | upper }}")
        assert result == "HELLO"

    def test_render_file(self, builder: RouteBuilder, tmp_path) -> None:
        template = tmp_path / "tmpl.txt"
        template.write_text("Hi {{ name }}!", encoding="utf-8")
        result = builder.render_file(template, {"name": "Bob"})
        assert result == "Hi Bob!"

    def test_render_email(self, builder: RouteBuilder) -> None:
        subject_tmpl = "Welcome {{ name }}"
        body_tmpl = "Hello {{ name }}, your id is {{ user_id }}."
        subject, body = builder.render_email(
            subject_tmpl, body_tmpl, {"name": "Alice", "user_id": 42}
        )
        assert subject == "Welcome Alice"
        assert body == "Hello Alice, your id is 42."

    def test_render_document_writes_file(self, builder: RouteBuilder, tmp_path) -> None:
        tmpl = tmp_path / "src.txt"
        out = tmp_path / "subdir" / "out.txt"
        tmpl.write_text("Generated: {{ value }}", encoding="utf-8")
        bytes_written = builder.render_document(tmpl, out, {"value": "X"})
        assert out.exists()
        assert out.read_text(encoding="utf-8") == "Generated: X"
        assert bytes_written == len("Generated: X")

    def test_render_template_with_loop(self, builder: RouteBuilder) -> None:
        tmpl = "{% for x in items %}{{ x }},{% endfor %}"
        result = builder.template_render_str(tmpl, {"items": [1, 2, 3]})
        assert result == "1,2,3,"

    def test_render_template_with_conditional(self, builder: RouteBuilder) -> None:
        tmpl = "{% if x > 5 %}big{% else %}small{% endif %}"
        assert builder.template_render_str(tmpl, {"x": 10}) == "big"
        assert builder.template_render_str(tmpl, {"x": 1}) == "small"

    def test_render_template_unicode(self, builder: RouteBuilder) -> None:
        result = builder.template_render_str("Привет {{ name }} 🚀", {"name": "Мир"})
        assert result == "Привет Мир 🚀"

    def test_render_template_missing_var_returns_empty(self, builder: RouteBuilder) -> None:
        # Jinja by default returns empty for undefined
        result = builder.template_render_str("{{ undefined_var }}")
        assert result == ""

    def test_render_template_empty_context(self, builder: RouteBuilder) -> None:
        result = builder.template_render_str("Static text", {})
        assert result == "Static text"

    def test_render_template_no_context(self, builder: RouteBuilder) -> None:
        result = builder.template_render_str("Hello", None)
        assert result == "Hello"

    def test_register_filter_chainable(self, builder: RouteBuilder) -> None:
        result = builder.register_filter("double", lambda x: x * 2)
        assert result is builder  # returns self for chaining
        assert builder.template_render_str("{{ 5 | double }}") == "10"

    def test_template_engine_in_mro(self, builder: RouteBuilder) -> None:
        mro_names = [c.__name__ for c in builder.__class__.__mro__]
        assert "TemplateEngineMixin" in mro_names
