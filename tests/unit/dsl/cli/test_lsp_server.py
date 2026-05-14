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
    # У LanguageServer есть метод publish_diagnostics.
    assert hasattr(server, "publish_diagnostics")


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
