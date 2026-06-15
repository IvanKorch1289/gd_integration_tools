"""Smoke-тесты для LSP-сервера DSL.

Wave ``[wave:s6/k3-dsl-linter-lsp]``.

Покрытие:

* импортируется модуль ``lsp_server`` без pygls (graceful);
* ``main()`` возвращает 2 при отсутствии pygls;
* при наличии pygls — ``create_server()`` создаёт LanguageServer;
* ``_publish_diagnostics`` вызывает linter и публикует diagnostics.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest


def test_lsp_module_importable() -> None:
    """Модуль импортируется даже без pygls (lazy import)."""
    import src.backend.dsl.cli.lsp_server as lsp

    assert hasattr(lsp, "create_server")
    assert hasattr(lsp, "main")


def test_main_returns_2_without_pygls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без pygls main() возвращает exit-code 2."""
    import src.backend.dsl.cli.lsp_server as lsp

    monkeypatch.setattr(lsp, "_try_import_pygls", lambda: None)
    assert lsp.main() == 2


def test_create_server_with_pygls() -> None:
    """С pygls create_server возвращает LanguageServer instance."""
    pytest.importorskip("pygls")
    from src.backend.dsl.cli.lsp_server import create_server

    server = create_server()
    assert server is not None
    # pygls 2.x: метод publish-diagnostics называется
    # ``text_document_publish_diagnostics``. Совместимость с 1.x
    # через старое имя ``publish_diagnostics`` — fallback в коде.
    assert hasattr(server, "text_document_publish_diagnostics") or hasattr(
        server, "publish_diagnostics"
    )


@pytest.mark.asyncio
async def test_publish_diagnostics_calls_linter(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``_publish_diagnostics`` вызывает linter и публикует diagnostics."""
    pytest.importorskip("pygls")
    from src.backend.dsl.cli import lsp_server

    yaml_path = tmp_path / "x.dsl.yaml"
    yaml_path.write_text("invalid_root_only", encoding="utf-8")

    published: list[tuple[str, list]] = []

    class _FakeLS:
        def publish_diagnostics(self, uri: str, diagnostics: list) -> None:
            published.append((uri, diagnostics))

    await lsp_server._publish_diagnostics(_FakeLS(), f"file://{yaml_path}")

    assert published, "publish_diagnostics не был вызван"
    assert published[0][0].startswith("file://")


def test_completion_tables_non_empty() -> None:
    """ROUTE_COMPLETIONS + STEP_COMPLETIONS заполнены и без дублей."""
    from tools.dsl_lsp.schema_completion import ROUTE_COMPLETIONS, STEP_COMPLETIONS

    assert len(ROUTE_COMPLETIONS) >= 8
    assert len(STEP_COMPLETIONS) >= 15
    # Уникальные ключи (label → detail).
    route_keys = [k for k, _ in ROUTE_COMPLETIONS]
    step_keys = [k for k, *_ in STEP_COMPLETIONS]
    assert len(route_keys) == len(set(route_keys)), "дубли в ROUTE_COMPLETIONS"
    assert len(step_keys) == len(set(step_keys)), "дубли в STEP_COMPLETIONS"
    # Базовые ожидаемые ключи присутствуют.
    assert "from" in route_keys
    assert "steps" in route_keys
    assert "to" in route_keys
    assert "call_function" in step_keys
    assert "dispatch_action" in step_keys
    assert "invoke_workflow" in step_keys


def test_completion_details_non_empty() -> None:
    """Detail-строка для каждого ключа содержит описание (>= 8 символов)."""
    from tools.dsl_lsp.schema_completion import ROUTE_COMPLETIONS, STEP_COMPLETIONS

    for key, detail, *_ in (*ROUTE_COMPLETIONS, *STEP_COMPLETIONS):
        assert isinstance(detail, str)
        assert len(detail) >= 8, f"detail для {key!r} слишком короткий: {detail!r}"


def test_build_completion_list_route_toml() -> None:
    """Для route.toml возвращаются только route-ключи без snippet."""
    pytest.importorskip("pygls")
    from lsprotocol import types as lsp_types

    from src.backend.dsl.cli.lsp_server import _build_completion_list
    from tools.dsl_lsp.schema_completion import ROUTE_COMPLETIONS, STEP_COMPLETIONS

    result = _build_completion_list(
        "file:///project/routes/foo/route.toml",
        lsp_types,
        ROUTE_COMPLETIONS,
        STEP_COMPLETIONS,
    )
    labels = {item.label for item in result.items}
    assert "from" in labels
    assert "steps" in labels
    assert "call_function" not in labels
    assert all(item.insert_text is None for item in result.items)


def test_build_completion_list_dsl_yaml() -> None:
    """Для *.dsl.yaml возвращаются только step'ы со snippet."""
    pytest.importorskip("pygls")
    from lsprotocol import types as lsp_types

    from src.backend.dsl.cli.lsp_server import _build_completion_list
    from tools.dsl_lsp.schema_completion import ROUTE_COMPLETIONS, STEP_COMPLETIONS

    result = _build_completion_list(
        "file:///project/routes/foo/bar.dsl.yaml",
        lsp_types,
        ROUTE_COMPLETIONS,
        STEP_COMPLETIONS,
    )
    labels = {item.label for item in result.items}
    assert "call_function" in labels
    assert "proxy" in labels
    assert "from" not in labels
    assert all(
        item.insert_text_format == lsp_types.InsertTextFormat.Snippet
        for item in result.items
    )


def test_build_completion_list_unknown_file() -> None:
    """Для неизвестного файла возвращаются и route, и step completions."""
    pytest.importorskip("pygls")
    from lsprotocol import types as lsp_types

    from src.backend.dsl.cli.lsp_server import _build_completion_list
    from tools.dsl_lsp.schema_completion import ROUTE_COMPLETIONS, STEP_COMPLETIONS

    result = _build_completion_list(
        "file:///project/readme.md", lsp_types, ROUTE_COMPLETIONS, STEP_COMPLETIONS
    )
    labels = {item.label for item in result.items}
    assert "from" in labels
    assert "call_function" in labels
