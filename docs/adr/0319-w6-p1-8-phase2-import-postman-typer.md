# ADR-0319 — W6 P1-8 Phase 2: argparse → typer migration (`tools/import_postman.py`)

* Статус: **Accepted** (cycle 152).
* Связано с: MINIMAX W6 P1-8 (typer+rich CLI); ADR-0318 (Phase 1 pilot).
* Pilot #2 для ~89 argparse tools.

## Контекст

ADR-0318 (Phase 1) мигрировал `tools/import_wsdl.py` (90 LOC) на typer+rich.
Cycle 152 Phase 2 применяет тот же pattern к `tools/import_postman.py`
(110 LOC, простой argparse). Подтверждает воспроизводимость pattern.

## Решение

### Что сделано

**`tools/import_postman.py`** (110 → 169 LOC, +59):
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- `sys.stdout.write(f"[...]")` → `_console.print(f"[bold cyan]...")`.
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.

### Pattern validation (ADR-0318 → ADR-0319)

Pattern из ADR-0318 применился **без изменений** на 2 разных tools:

| Tool | LOC | CLI args | Migration complexity |
|---|---|---|---|
| `import_wsdl.py` | 90 → 132 | `--url, --connector, --write, --output-dir` | simple |
| `import_postman.py` | 110 → 169 | `--file, --connector, --write, --output-dir` | simple |

**Pattern proven**: 1 commit per tool, ~30 минут на tool, +50-60 LOC net (больше boilerplate для typer+rich). Pattern можно тиражировать.

### Тесты

`tests/unit/tools/test_w6_p1_8_import_postman_typer.py` (7 тестов):
- TestImportPostmanTyperMigration (4): app is typer, --help formatted,
  no argparse, no sys.stdout.write.
- TestBackwardCompat (2): main([--help]), main([]) → exit codes.
- TestImportsWork (1): module imports work.

## Roadmap для остальных ~88 argparse tools

Pattern готов. Следующие кандидаты (отсортированы по простоте):

**Phase 3 (отдельные commits, ~cycle 156+)**:
1. `tools/check_env_example.py` (157 LOC) — простой config-validation CLI.
2. `tools/check_dsn_drivers.py` (133 LOC) — простой проверка DSN.
3. `tools/discover_plugin_capabilities.py` (241 LOC) — частично typer (S62 W3).

**Phase 4 (medium complexity)**:
- `tools/codegen_plugin.py` (484), `tools/check_docstrings.py` (519),
  `tools/config_audit.py` (486).

**Phase 5 (high complexity, separate sprint)**:
- `tools/codegen_settings.py` (1107), `tools/pre_prod_check.py` (898),
  `tools/gen_dsl_stubs.py` (875).

## Альтернативы (отклонённые)

* **Один commit для всех 88 tools**: отклонено — большой diff, трудно review.
* **Keep argparse навсегда**: отклонено — ADR-0084 explicit preference.
* **Replace typer с click**: typer==click-native CLI, переход ничего не даёт.

## Verification

```
compileall -q tools/import_postman.py                                       → exit 0
uv run python tools/import_postman.py --help                                → typer-formatted help
uv run python tools/import_postman.py                                       → shows help
pytest tests/unit/tools/test_w6_p1_8_import_postman_typer.py                → 7 passed
pytest tests/unit/tools/test_w6_p1_8_import_{wsdl,postman}_typer.py          → 15 passed
ruff check --select F401,F841,F811,E9                                       → All checks passed!
```

## Связанные изменения

* **`tools/import_postman.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_import_postman_typer.py`** — новый (7 тестов).
* **`docs/adr/0319-w6-p1-8-phase2-import-postman-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0319 зарегистрирован (112 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084, ADR-0318 (Phase 1), ADR-0319 (Phase 2),
cycle 152.