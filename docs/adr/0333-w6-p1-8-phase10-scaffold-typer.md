# ADR-0333 — W6 P1-8 Phase 10: `tools/scaffold.py` argparse → typer (subcommands) + structlog Py2 syntax fix

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W6 P1-8; ADR-0318 (Phase 1); ADR-0319 (Phase 2);
  ADR-0322 (Phase 3); ADR-0323 (Phase 4); ADR-0324 (Phase 5);
  ADR-0325 (Phase 6); ADR-0326 (Phase 7); ADR-0327 (Phase 8);
  ADR-0332 (Phase 9); W5 P1-7 (structlog default backend).

## Контекст

W6 P1-8 momentum: 9 tools подряд мигрированы на typer+rich pattern. Phase 10
мигрирует `tools/scaffold.py` (subparsers pattern с 3 subcommands:
processor/service/route). Дополнительно — **critical pre-existing Py2 syntax
fix** обнаружен во время verification (W5 P1-7 structlog_backend.py имел 2
unparenthesized `except A, B:` clauses, пропущенных W0 P0-BLOCKER миграцией).

## Решение

### Что сделано

**`tools/scaffold.py`** (207 → 233 LOC, +26):
- `argparse.ArgumentParser` + `add_subparsers` → `typer.Typer` + `@app.command(name=...)`.
- 3 subcommands: `processor`, `service`, `route` (каждый — отдельная `@app.command`).
- `args.func(args)` callback pattern → direct typer command functions.
- `print(...)` → `_console.print("[red]ERROR: ...[/]")` / `[green]Created:[/]`.
- `sys.exit(1)` для "файл существует" → `raise typer.Exit(code=1)`.
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.

**`src/backend/infrastructure/logging/structlog_backend.py`** (CRITICAL FIX):
- **Line 68**: `except TypeError, ValueError:` → `except (TypeError, ValueError):`
- **Line 298**: `except ImportError, AttributeError:` → `except (ImportError, AttributeError):`
- Это 2 pre-existing SyntaxError из W5 P1-7 (3b41edeb4) — модуль не компилировался на
  Python 3.x без фикса. Обнаружено при pytest collection (structlog_backend.py
  импортируется через logging factory во многих tests).

### Pattern validation (10 tools)

| Tool | LOC (orig→new) | Args | Complexity |
|---|---|---|---|
| Phase 1-9 (9 tools) | various | various | various |
| `scaffold.py` (Phase 10) | 207 → 233 | 3 subcommands | medium |

Pattern **proven на 10 tools**. Typer subcommands pattern (`@app.command(name=...)`)
validated на scaffold.py.

### Тесты

`tests/unit/tools/test_w6_p1_8_phase10_scaffold_typer.py` (10 тестов):
- TestScaffoldTyperMigration (4): app is typer, no argparse, --help formatted,
  subcommand --help.
- TestBackwardCompat (4): main(['--help']), main(['processor', '--dry-run']),
  main(['service', '--dry-run']), main(['route', '--dry-run']).
- TestSafety (1): --dry-run НЕ создаёт файлы.
- TestImportsWork (1): module imports + 3 templates exposed.

## Verification

```
compileall -q src/backend/infrastructure/logging/                    → exit 0 (FIX!)
compileall -q src/ extensions/ scripts/ tools/ tests/                  → exit 0
python tools/scaffold.py processor --help                            → typer-formatted
python tools/scaffold.py processor --name X --dry-run               → DRY-RUN safe
pytest tests/unit/tools/test_w6_p1_8_phase10_scaffold_typer.py        → 10 passed
ruff check tools/scaffold.py                                        → All checks passed
```

## Связанные изменения

* **`tools/scaffold.py`** — мигрирован argparse (subparsers) → typer (3 subcommands).
* **`src/backend/infrastructure/logging/structlog_backend.py`** — 2 Py2-syntax фикса
  (pre-existing bug от W5 P1-7, missed by W0 P0-BLOCKER миграцией).
* **`tests/unit/tools/test_w6_p1_8_phase10_scaffold_typer.py`** — новый (10 тестов).
* **`docs/adr/0333-w6-p1-8-phase10-scaffold-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0333 зарегистрирован (126 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

## Lesson learned

W6 P1-8 verification (10 tests для scaffold.py) выявил pre-existing prod
SyntaxError в `structlog_backend.py` — модуль был SyntaxError на Python 3.x
без fix. Это подтверждает критичность **continuous verification**: pytest
collection (которая импортирует ВСЕ модули через test imports) поймал
баг, который пропустил compileall при `compileall -q src/backend`.

W0 P0-BLOCKER migration (commit 38b4992e6) обработал 234 строки в 177 файлах,
но не покрыл `src/backend/infrastructure/logging/structlog_backend.py` —
файл был добавлен позднее (W5 P1-7 commit 3b41edeb4) с pre-existing Py2 syntax.

Фикс минимальный (2 строки), но **critical** — модуль не работал в runtime.

Refs: MINIMAX W6 P1-8, ADR-0084, ADR-0318-ADR-0327 (Phases 1-8), ADR-0332 (Phase 9),
ADR-0312 (W5 P1-7 structlog default), cycle 153.
