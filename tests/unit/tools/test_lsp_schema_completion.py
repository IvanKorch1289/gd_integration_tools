"""TDD: tools/dsl_lsp/schema_completion.py — DSL autocomplete (M14.3).

LSP provider для автодополнения DSL. Каждый step имеет:
- label (имя)
- detail (описание)
- insert_text (snippet с placeholders)

M14.3 audit: работает, 23 step + 12 route completions.

ADR-0369 (C4, cycle 172): канон — **имя YAML-шага = имя публичного метода
``RouteBuilder``**. Completion не должен предлагать несуществующие шаги и
несуществующие параметры.
"""

from __future__ import annotations

from typing import Any


class TestSchemaCompletion:
    def test_step_completions_have_required_fields(self) -> None:
        """Каждый step completion имеет label, detail, insert_text."""
        from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

        for entry in STEP_COMPLETIONS:
            assert len(entry) == 3, f"entry должен быть 3-tuple, got {entry}"
            label, detail, insert_text = entry
            assert isinstance(label, str) and label, f"label пустой: {entry}"
            assert isinstance(detail, str) and detail, f"detail пустой: {entry}"
            assert isinstance(insert_text, str) and insert_text, (
                f"insert_text пустой: {entry}"
            )

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
                assert isinstance(snippet, dict) and "properties" in snippet, (
                    f'snippet "{label}" not JSON-Schema: {snippet}'
                )

    def test_step_labels_are_unique(self) -> None:
        from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

        labels = [label for label, _, _ in STEP_COMPLETIONS]
        assert len(labels) == len(set(labels)), "дубликаты step-labels"


class TestStepCompletionApiFidelity:
    """ADR-0369: completion обязан соответствовать реальному API RouteBuilder."""

    def test_step_labels_are_public_route_builder_methods(self) -> None:
        """Каждый предложенный шаг — публичный метод ``RouteBuilder``."""
        from src.backend.dsl.builder import RouteBuilder
        from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

        phantom = [
            label for label, _, _ in STEP_COMPLETIONS if not hasattr(RouteBuilder, label)
        ]
        assert not phantom, f"шаги без метода RouteBuilder: {phantom}"

    def test_removed_phantom_steps_are_absent(self) -> None:
        from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

        labels = {label for label, _, _ in STEP_COMPLETIONS}
        for phantom in ("validate_request", "try_catch", "sink_publish"):
            assert phantom not in labels, f"{phantom} не существует в RouteBuilder"

    def test_snippet_params_are_accepted_by_builder_method(self) -> None:
        """Ни snippet, ни его ``required`` не предлагают несуществующие kwargs."""
        import inspect

        from src.backend.dsl.builder import RouteBuilder
        from tools.dsl_lsp.schema_completion import STEP_SCHEMA_SNIPPETS

        problems: list[str] = []
        for label, snippet in STEP_SCHEMA_SNIPPETS.items():
            method = getattr(RouteBuilder, label, None)
            if method is None:
                problems.append(f"{label}: нет метода RouteBuilder")
                continue
            signature = inspect.signature(method)
            if any(
                p.kind is inspect.Parameter.VAR_KEYWORD
                for p in signature.parameters.values()
            ):
                continue
            accepted = set(signature.parameters)
            schema: dict[str, Any] = dict(snippet)  # type: ignore[arg-type]
            keys = set(schema.get("required") or ()) | set(
                (schema.get("properties") or {}).keys()
            )
            unknown = sorted(keys - accepted)
            if unknown:
                problems.append(f"{label}: неизвестные параметры {unknown}")
        assert not problems, "; ".join(problems)

    def test_rpa_steps_are_offered(self) -> None:
        """RPA-шаги обязаны быть в автодополнении (ADR-0369, решение D6)."""
        from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

        labels = {label for label, _, _ in STEP_COMPLETIONS}
        expected = {
            "csv_read",
            "csv_write",
            "email_read",
            "file_delete",
            "file_list",
            "ftp_upload",
            "http_request",
            "terminal_exec",
            "browser_launch",
            "wait_for_selector",
            "print_pdf",
        }
        assert expected <= labels, f"не хватает RPA-шагов: {sorted(expected - labels)}"


class TestCatalogDrivenCompletions:
    """ADR-0399: completion строится из каталога шагов (не из хардкод-списка)."""

    def test_completions_cover_whole_catalog(self) -> None:
        """Каждый YAML-шаг каталога присутствует в completion."""
        from src.backend.dsl.builders.step_catalog import builder_step_names
        from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

        labels = {label for label, *_ in STEP_COMPLETIONS}
        missing = sorted(set(builder_step_names()) - labels)
        assert not missing, f"completion не покрывает шаги: {missing[:10]}"

    def test_generated_entries_have_snippet(self) -> None:
        """Сгенерированные записи содержат валидный insert_text."""
        from src.backend.dsl.builders.step_catalog import builder_step_names
        from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

        entries = {label: snippet for label, _detail, snippet in STEP_COMPLETIONS}
        steps = set(builder_step_names())
        for step in sorted(steps):
            snippet = entries[step]
            assert snippet.startswith(f"{step}:"), (
                f"{step}: snippet должен начинаться с имени шага"
            )

    def test_static_list_remains_fallback(self) -> None:
        """Статический список сохранён как fallback (ADR-0399)."""
        from tools.dsl_lsp.schema_completion import _STATIC_STEP_COMPLETIONS

        assert len(_STATIC_STEP_COMPLETIONS) >= 15
        labels = [label for label, _, _ in _STATIC_STEP_COMPLETIONS]
        assert "proxy" in labels
        assert len(labels) == len(set(labels))
