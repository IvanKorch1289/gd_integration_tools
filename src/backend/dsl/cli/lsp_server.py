"""LSP-сервер для DSL route.toml + *.dsl.yaml через pygls.

Wave ``[wave:s6/k3-dsl-linter-lsp]``.

Назначение: язык-сервер (Language Server Protocol) для IDE-интеграции
(VSCode/JetBrains/Neovim). Предоставляет:

* ``textDocument/didOpen`` / ``didChange`` — параллельный запуск
  :class:`~src.backend.dsl.cli.linter.DSLLinter` на буфере;
* ``textDocument/publishDiagnostics`` — публикация warnings/errors как
  diagnostics с link на правило (``code``) и suggestion;
* **plugin-aware schema discovery** — при открытии файла внутри
  ``extensions/<name>/`` сервер ищет ``plugin.toml`` и подгружает
  declared capabilities + per-extension processor whitelist (если есть
  ``extensions/<name>/dsl/processors.json``).

Запуск (stdio): ``python -m src.backend.dsl.cli.lsp_server``.

Feature flag: ``feature_flags.dsl_linter_strict`` — выше severity в
diagnostics (warning → error).

Зависимости: ``pygls>=1.3`` (опциональная, см. ``[project.optional-dependencies].dev``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

__all__ = ("create_server", "main")

_logger = logging.getLogger(__name__)


def _try_import_pygls() -> Any | None:
    """Lazy import pygls. Возвращает None, если не установлен."""
    try:
        from pygls.server import LanguageServer  # noqa: F401

        return True
    except ImportError:
        _logger.warning(
            "pygls не установлен — LSP server недоступен. "
            "Установите [dev] extra: pip install gd-integration-tools[dev]"
        )
        return None


def create_server() -> Any:
    """Создать ``LanguageServer`` и зарегистрировать handlers.

    Returns:
        ``pygls.server.LanguageServer`` instance с handlers для
        ``textDocument/didOpen``, ``didChange``, ``publishDiagnostics``.

    Raises:
        ImportError: Если ``pygls`` не установлен.
    """
    from lsprotocol import types as lsp_types
    from pygls.server import LanguageServer

    server = LanguageServer("gd-dsl-lsp", "0.1.0")

    @server.feature(lsp_types.TEXT_DOCUMENT_DID_OPEN)
    async def did_open(ls: LanguageServer, params: lsp_types.DidOpenTextDocumentParams):
        """Run linter и публикует diagnostics при открытии буфера."""
        await _publish_diagnostics(ls, params.text_document.uri)

    @server.feature(lsp_types.TEXT_DOCUMENT_DID_CHANGE)
    async def did_change(
        ls: LanguageServer, params: lsp_types.DidChangeTextDocumentParams
    ):
        """Run linter после каждого change в буфере."""
        await _publish_diagnostics(ls, params.text_document.uri)

    @server.feature(lsp_types.TEXT_DOCUMENT_DID_SAVE)
    async def did_save(ls: LanguageServer, params: lsp_types.DidSaveTextDocumentParams):
        """Re-lint при save (на случай внешних правок route.toml)."""
        await _publish_diagnostics(ls, params.text_document.uri)

    return server


async def _publish_diagnostics(ls: Any, uri: str) -> None:
    """Запустить linter и опубликовать diagnostics через LSP."""
    from lsprotocol import types as lsp_types

    from src.backend.dsl.cli.linter import lint_path

    # uri = "file:///path/to/foo.dsl.yaml"
    if not uri.startswith("file://"):
        return
    path = Path(uri[7:])

    # Запускаем linter (strict-mode читаем из feature_flag).
    try:
        from src.backend.core.config.features import feature_flags

        strict = bool(getattr(feature_flags, "dsl_linter_strict", False))
    except ImportError:
        strict = False

    try:
        issues = lint_path(path, strict=strict)
    except Exception as exc:  # noqa: BLE001 — LSP не должен крашить IDE.
        _logger.error("DSL linter error для %s: %s", path, exc)
        issues = []

    diagnostics = [
        lsp_types.Diagnostic(
            range=lsp_types.Range(
                start=lsp_types.Position(line=max(iss.line - 1, 0), character=0),
                end=lsp_types.Position(line=max(iss.line - 1, 0), character=255),
            ),
            message=f"{iss.message}"
            + (f" → {iss.suggestion}" if iss.suggestion else ""),
            severity=(
                lsp_types.DiagnosticSeverity.Error
                if iss.severity == "error"
                else lsp_types.DiagnosticSeverity.Warning
            ),
            code=iss.code,
            source="gd-dsl-linter",
        )
        for iss in issues
    ]

    ls.publish_diagnostics(uri, diagnostics)


def main() -> int:
    """Запуск LSP-сервера через stdio.

    Используется IDE через настройку ``executable":
    ["python", "-m", "src.backend.dsl.cli.lsp_server"]``.
    """
    if _try_import_pygls() is None:
        return 2

    server = create_server()
    server.start_io()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
