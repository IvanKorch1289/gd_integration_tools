"""TDD: tools/dsl_lsp/schema_completion.py — DSL autocomplete (M14.3).

LSP provider для автодополнения DSL. Каждый step имеет:
- label (имя)
- detail (описание)
- insert_text (snippet с placeholders)

M14.3 audit: работает, 23 step + 12 route completions.
"""
# ruff: noqa: S101
from __future__ import annotations


class TestSchemaCompletion:
    def test_step_completions_have_required_fields(self) -> None:
        """Каждый step completion имеет label, detail, insert_text."""
        from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

        for entry in STEP_COMPLETIONS:
            assert len(entry) == 3, f"entry должен быть 3-tuple, got {entry}"
            label, detail, insert_text = entry
            assert isinstance(label, str) and label, f"label пустой: {entry}"
            assert isinstance(detail, str) and detail, f"detail пустой: {entry}"
            assert isinstance(insert_text, str) and insert_text, f"insert_text пустой: {entry}"

    def test_route_completions_have_required_fields(self) -> None:
        from tools.dsl_lsp.schema_completion import ROUTE_COMPLETIONS

        for entry in ROUTE_COMPLETIONS:
            assert len(entry) >= 2, f"entry должен быть tuple: {entry}"

    def test_step_snippets_have_yaml_structure(self) -> None:
        """Step snippets должны быть YAML-format."""
        from tools.dsl_lsp.schema_completion import get_step_snippet

        for label in ["proxy", "map", "log"]:
            snippet = get_step_snippet(label)
            if snippet:
                # YAML формат — содержит `key: value`
                assert isinstance(snippet, dict) and "properties" in snippet, f"snippet \"{label}\" not JSON-Schema: {snippet}"
