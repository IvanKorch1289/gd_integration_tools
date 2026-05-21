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

__all__ = ("create_server", "main", "ROUTE_KEY_COMPLETIONS", "STEP_KEY_COMPLETIONS")

_logger = logging.getLogger(__name__)

#: Ключи верхнего уровня в `route.toml` / `*.dsl.yaml` для автокомплита.
ROUTE_KEY_COMPLETIONS: tuple[tuple[str, str], ...] = (
    ("from", "Источник route (HTTP/Email/MQ/CDC/Webhook/Stream/...)."),
    ("steps", "Массив step-операций, выполняемых последовательно."),
    ("to", "Терминал route (response/sink/MQ/...) — финальная остановка."),
    ("on_error", "Глобальный обработчик ошибок: dlq | retry | fail | warn."),
    ("policy", "Idempotency/rate-limit/circuit-breaker для всего route."),
    ("schedule", "Cron / interval для scheduled-route."),
    ("requires_core", "SemVer-ограничение ядра."),
    ("requires_plugins", "Список плагинов с SemVer."),
    ("capabilities", "Список capabilities (V11) — db.read/net.outbound/..."),
    ("tenant_aware", "Bool — учитывать tenant-контекст."),
    ("feature_flag", "Имя feature_flag для default-OFF включения."),
    ("slo", "Service Level Objective: latency_p95_ms, error_budget_pct."),
)

#: Типы step-операций для автокомплита внутри массива `steps`.
STEP_KEY_COMPLETIONS: tuple[tuple[str, str], ...] = (
    ("proxy", "Прокси-запрос на upstream без бизнес-логики."),
    ("redirect", "HTTP-redirect 30x на target URL."),
    ("call_function", "Вызов Python-функции 'module:fn' через whitelist."),
    ("dispatch_action", "Service Activator — диспетчер action в sync/async/bg/api/sse/ws."),
    ("transform", "JMESPath/JSONata/JSONLogic трансформация body/header."),
    ("choice", "EIP Content-Based Router — when/otherwise ветвление."),
    ("parallel", "EIP Scatter-Gather — параллельное выполнение branches."),
    ("try_catch", "Try-catch с компенсацией / DLQ-handoff."),
    ("saga", "Saga-step (Temporal compensation)."),
    ("invoke_workflow", "Temporal/Lite workflow invocation."),
    ("crud_create", "CRUD create entity через repository."),
    ("crud_read", "CRUD read by id или filter."),
    ("crud_update", "CRUD update by id."),
    ("crud_delete", "CRUD delete by id."),
    ("publish_event", "Publish в MQ (Kafka/RabbitMQ/NATS/Redis Streams)."),
    ("notify_cascade", "Email/SMS/Telegram cascade notification."),
    ("audit", "Audit-event в audit-trail."),
    ("validate_response", "Pydantic-валидация response от внешнего API."),
    ("db_query_external", "SELECT в внешней БД через capability db.read."),
    ("db_call_procedure", "Вызов хранимой процедуры через capability."),
    ("get_setting", "Прочитать конфиг по path → body.x."),
    ("sink_publish", "Публикация в sink (S3/Kafka/WebDAV/...)."),
)


def _try_import_pygls() -> Any | None:
    """Lazy import pygls. Возвращает None, если не установлен."""
    try:
        from pygls.lsp.server import LanguageServer  # noqa: F401

        return True
    except ImportError:
        _logger.warning(
            "pygls не установлен — LSP server недоступен. "
            "Установите [lsp] extra: pip install gd-integration-tools[lsp]"
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
    from pygls.lsp.server import LanguageServer

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

    @server.feature(
        lsp_types.TEXT_DOCUMENT_COMPLETION,
        lsp_types.CompletionOptions(trigger_characters=[".", ":", " "]),
    )
    def completion(
        ls: LanguageServer, params: lsp_types.CompletionParams
    ) -> lsp_types.CompletionList:
        """Автокомплит для route.toml + *.dsl.yaml ключей.

        Простой статический list — Tier 1 (роуты сверху + типы step-ов).
        Tier 2 (контекстно-зависимый по cursor-line prefix) — carryover S17.
        """
        items: list[lsp_types.CompletionItem] = []
        for key, detail in ROUTE_KEY_COMPLETIONS:
            items.append(
                lsp_types.CompletionItem(
                    label=key,
                    kind=lsp_types.CompletionItemKind.Property,
                    detail=detail,
                )
            )
        for key, detail in STEP_KEY_COMPLETIONS:
            items.append(
                lsp_types.CompletionItem(
                    label=key,
                    kind=lsp_types.CompletionItemKind.Function,
                    detail=detail,
                )
            )
        return lsp_types.CompletionList(is_incomplete=False, items=items)

    @server.feature(lsp_types.TEXT_DOCUMENT_HOVER)
    def hover(
        ls: LanguageServer, params: lsp_types.HoverParams
    ) -> lsp_types.Hover | None:
        """Hover-описание поля под курсором (Tier 1 — статический lookup)."""
        document = ls.workspace.get_text_document(params.text_document.uri)
        line_idx = params.position.line
        if line_idx >= len(document.lines):
            return None
        line = document.lines[line_idx]
        # Извлекаем первое слово (ключ перед `:` или `=`).
        token = line.lstrip().split(":", 1)[0].split("=", 1)[0].strip(" -")
        lookup = {k: d for k, d in (*ROUTE_KEY_COMPLETIONS, *STEP_KEY_COMPLETIONS)}
        detail = lookup.get(token)
        if detail is None:
            return None
        return lsp_types.Hover(
            contents=lsp_types.MarkupContent(
                kind=lsp_types.MarkupKind.Markdown,
                value=f"**{token}** — {detail}",
            )
        )

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

    # pygls 2.x: метод называется text_document_publish_diagnostics;
    # для тестового _FakeLS оставлен fallback на старое publish_diagnostics.
    publisher = getattr(
        ls, "text_document_publish_diagnostics", None
    ) or getattr(ls, "publish_diagnostics", None)
    if publisher is None:
        _logger.warning("LS has no publish_diagnostics method — skipping")
        return
    publisher(uri, diagnostics)


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
