# ADR-0325 — W6 P1-8 Phase 6: `tools/migrate_to_structlog.py` argparse → typer

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W6 P1-8; ADR-0318 (Phase 1); ADR-0319 (Phase 2);
  ADR-0322 (Phase 3); ADR-0323 (Phase 4); ADR-0324 (Phase 5);
  W5 P1-7 (structlog default migration).

## Контекст

W6 P1-8 momentum продолжается: 6 tools подряд мигрированы по proven pattern.
Phase 6 мигрирует `tools/migrate_to_structlog.py` — auto-migration codemod
который был **центральным** для W5 P1-7 structlog default migration (см. ADR-0312).
Сам инструмент оставался на argparse пока что.

## Решение

### Что сделано

**`tools/migrate_to_structlog.py`** (282 → 314 LOC, +32):
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- `print(...)` → `_console.print("[green]CHANGE[/]: ...")` (rich color codes).
- `print(..., file=sys.stderr)` → `_console.print("[red]ERROR[/]: ...")` (rich).
- Positional `paths` argument + `--dry-run` flag сохранены.
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.
- Removed unused `import sys` (заменён на rich.console).

### Pattern validation (6 tools)

| Tool | LOC (orig→new) | CLI args | Complexity |
|---|---|---|---|
| `import_wsdl.py` (Phase 1) | 90 → 132 | 4 flags | simple |
| `import_postman.py` (Phase 2) | 110 → 169 | 4 flags | simple |
| `check_env_example.py` (Phase 3) | 157 → 187 | 1 flag | trivial |
| `check_dsn_drivers.py` (Phase 4) | 133 → 152 | 1 flag | trivial |
| `s86_workflow_sandbox_guard.py` (Phase 5) | 143 → 178 | 2 flags | trivial |
| `migrate_to_structlog.py` (Phase 6) | 282 → 314 | 1 arg + 1 flag | medium |

Pattern **proven на 6 tools** (3 trivial + 2 simple + 1 medium). Все варианты
argparse covered: positional args, boolean flags, path arguments.

### Тесты

`tests/unit/tools/test_w6_p1_8_phase6_migrate_to_structlog_typer.py` (8 тестов):
- TestMigrateToStructlogTyperMigration (3): app is typer, no argparse, --help formatted.
- TestBackwardCompat (4): main(['--help']), main(['--dry-run']),
  main(['--dry-run', '<file>']), main(['--dry-run', '<nonexistent>']).
- TestImportsWork (1): module imports + RE_IMPORT_LOGGING exposed.

### Idempotency check

После W5 P1-7 migration (~800 call sites auto-migrated) script уже не находит
новых изменений — `main(['--dry-run'])` → exit 0, "0 changed, N skipped".
Миграция теперь **zero-cost maintenance tool** для будущих logging imports.

## Roadmap для остальных ~83 argparse tools

**Phase 7 (cycle 156+)**:
- `tools/check_docstrings.py` (519 LOC) — pre-push gate (medium complexity).
- `tools/generate_adr_index.py` — ADR generation helper.

**Phase 8 (отдельный sprint)**:
- `tools/codegen_plugin.py` (484), `tools/codegen_settings.py` (1107),
  `tools/pre_prod_check.py` (898), `tools/gen_dsl_stubs.py` (875) — high complexity.

## Verification

```
compileall -q tools/migrate_to_structlog.py                                       → exit 0
python tools/migrate_to_structlog.py --help                                       → typer-formatted help
python tools/migrate_to_structlog.py --dry-run                                    → exit 0 (idempotent)
pytest tests/unit/tools/test_w6_p1_8_phase6_migrate_to_structlog_typer.py          → 8 passed
ruff check tools/migrate_to_structlog.py                                          → All checks passed!
```

## Связанные изменения

* **`tools/migrate_to_structlog.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_phase6_migrate_to_structlog_typer.py`** — новый (8 тестов).
* **`docs/adr/0325-w6-p1-8-phase6-migrate-to-structlog-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0325 зарегистрирован (118 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084, ADR-0318, ADR-0319, ADR-0312 (W5 P1-7),
ADR-0322, ADR-0323, ADR-0324, cycle 153.
