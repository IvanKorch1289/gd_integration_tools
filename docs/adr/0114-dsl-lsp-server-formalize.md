# ADR-0114 — DSL LSP server status + Makefile integration (Sprint 42 #1)

* Статус: Accepted (Sprint 42 W1, 2026-06-09)
* Связано с: PLAN.md §6 (S42 #1); src/backend/dsl/cli/lsp_server.py, tools/dsl_lsp/.

## Контекст

Sprint 42 DoD #1: "LSP server для DSL (pygls) — Автокомплит в VS Code".

### Existing state (до S42)

`src/backend/dsl/cli/lsp_server.py` (236 LOC, S6/K3):
- `textDocument/didOpen` / `didChange` — запуск `DSLLinter` на буфере.
- `textDocument/publishDiagnostics` — публикация warnings/errors
  с link на правило.
- `textDocument/completion` — YAML schema completion для step types
  и route keys (from `tools.dsl_lsp.schema_completion`).
- **Plugin-aware schema discovery** — при открытии файла в
  `extensions/<name>/` подгружает `plugin.toml` + per-extension
  processor whitelist.
- Запуск: `python -m src.backend.dsl.cli.lsp_server` (stdio).
- Feature flags: `dsl_linter_strict`, `lsp_server_published` (default-OFF).

### Tests

`tests/unit/dsl/cli/test_lsp_server.py` — **6/6 pass** в 0.49s.

### Dep

`pygls>=1.3` (опциональная, в `[dev]` extra) — installed в .venv.

## Проверка (2026-06-09)

```bash
$ python -m pytest tests/unit/dsl/cli/test_lsp_server.py
6 passed, 5 warnings in 0.49s

$ python -c "import pygls; print(pygls.__version__)"
[works — attribute error on __version__ but module loads]
```

LSP server is functional: tests pass, pygls available.

## Решение

**S42 #1 (LSP server) — closed via formalize** (W1 main):

1. **ADR-0114** — formalize existing LSP server (S6/K3 origin,
   236 LOC, 6/6 tests pass, plugin-aware).
2. **Makefile `lsp-server` target** — wrapper для удобного запуска
   stdio сервера с проверкой `pygls` availability.
3. **VS Code config snippet** — `.vscode/settings.json` example
   (документирует wire-up) в `docs/lsp/vscode-config.example.json`.

Никакого нового кода для самого LSP не требуется — feature complete
по S6. S42 W1 = formalize + integration glue.

## Альтернативы

| Альтернатива | За | Против | Решение |
|---|---|---|---|
| Rewrite LSP from scratch | Modern pygls API | 236 LOC working; rewrite = regression risk | Отклонено |
| Use Language Server Protocol SDK | Vendor-neutral | pygls = de-facto Python LSP stdlib | Отклонено |
| Add hover/definition features | Richer IDE UX | Out of S42 DoD (DoD = "автокомплит") | Deferred to S43+ |
| **Formalize + Makefile wrapper** | Audit-trail; integration glue | — | **Принято** |

## Последствия

* **Позитивные**:
  * LSP server формализован; future maintainer знает что S6 уже
    реализовал feature.
  * `make lsp-server` упрощает запуск (один command вместо
    `python -m ...`).
  * VS Code config example в docs ускоряет IDE wire-up.
* **Риски**:
  * LSP server в `lsp_server_published = default-OFF` feature flag —
    production users должны активировать явно. **Митигация**:
    docs указывают `feature_flags.lsp_server_published = true`.
  * S42 DoD "Автокомплит в VS Code" требует ручного VS Code config
    (не autoload). **Митигация**: example snippet в docs.

## Ссылки

* Код: `src/backend/dsl/cli/lsp_server.py` (236 LOC, S6 origin).
* Tests: `tests/unit/dsl/cli/test_lsp_server.py` (6/6 pass).
* Helper: `tools/dsl_lsp/schema_completion.py`.
* Schema: `tools/dsl_lsp/schemas/`.
* Linter: `src/backend/dsl/cli/linter.py` (вызывается LSP'ом).
* VS Code config: `docs/lsp/vscode-config.example.json` (new in W1).
* Makefile: `make lsp-server` (new in W1).
* Feature flag: `lsp_server_published` (default-OFF, см. `features/experimental.py`).
