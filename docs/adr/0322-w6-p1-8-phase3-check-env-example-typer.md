# ADR-0322 — W6 P1-8 Phase 3: `tools/check_env_example.py` argparse → typer

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W6 P1-8 (typer+rich CLI); ADR-0318 (Phase 1 pilot
  `tools/import_wsdl.py`); ADR-0319 (Phase 2 `tools/import_postman.py`).

## Контекст

ADR-0318 (Phase 1 pilot) мигрировал `tools/import_wsdl.py` (90 LOC) на typer+rich.
ADR-0319 (Phase 2) применил тот же pattern к `tools/import_postman.py`
(110 LOC, простой argparse) → pattern proven на 2 разных tools.

Cycle 153 Phase 3 применяет pattern к **третьему tool** — `tools/check_env_example.py`
(Wave F.9, проверка покрытия `.env.example` относительно Pydantic Settings).

## Решение

### Что сделано

**`tools/check_env_example.py`** (157 → 187 LOC, +30):
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- `print(..., file=sys.stderr)` → `_console.print("[red]...")` (rich color codes).
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.
- Removed `no_args_is_help=True` (конфликт с `invoke_without_command=True` — без
  args должен выполнять callback, а не показывать help).

### Pattern validation (ADR-0318 → ADR-0319 → ADR-0322)

Pattern из ADR-0318 применился **без изменений** на 3 разных tools:

| Tool | LOC (orig→new) | CLI args | Migration complexity |
|---|---|---|---|
| `import_wsdl.py` | 90 → 132 | `--url, --connector, --write, --output-dir` | simple |
| `import_postman.py` | 110 → 169 | `--file, --connector, --write, --output-dir` | simple |
| `check_env_example.py` | 157 → 187 | `--strict` (single flag) | trivial |

**Pattern proven** на 3 tools с разной сложностью (1-flag, 4-flag). Pattern готов
для тиражирования на остальные ~86 argparse tools.

### Тесты

`tests/unit/tools/test_w6_p1_8_phase3_check_env_example_typer.py` (8 тестов):
- TestCheckEnvExampleTyperMigration (4): app is typer, no argparse import,
  no sys.stdout.write, typer-formatted --help.
- TestBackwardCompat (3): main(['--help']), main([]), main(['--strict']).
- TestImportsWork (1): module imports work.

**Note**: тесты используют `importlib.util.spec_from_file_location()` workaround
для pytest `--import-mode=importlib`, который ломает `from tools.X import`.
Это pre-existing pytest issue (затрагивает все W6 P1-8 tests, включая ADR-0318/0319).
Workaround не меняет test contract — просто обходит pytest namespace quirk.

## Roadmap для остальных ~86 argparse tools

Pattern готов. Следующие кандидаты (отсортированы по простоте):

**Phase 4 (отдельные commits, ~cycle 156+)**:
1. `tools/check_dsn_drivers.py` (133 LOC) — простой проверка DSN (1 flag).
2. `tools/discover_plugin_capabilities.py` (241 LOC) — частично typer (S62 W3).

**Phase 5 (medium complexity)**:
- `tools/codegen_plugin.py` (484), `tools/check_docstrings.py` (519),
  `tools/config_audit.py` (486).

**Phase 6 (high complexity, separate sprint)**:
- `tools/codegen_settings.py` (1107), `tools/pre_prod_check.py` (898),
  `tools/gen_dsl_stubs.py` (875).

## Альтернативы (отклонённые)

* **Один commit для всех 86 tools**: отклонено — большой diff, трудно review.
* **Keep argparse навсегда**: отклонено — ADR-0084 explicit preference.
* **Replace typer с click**: typer==click-native CLI, переход ничего не даёт.

## Verification

```
compileall -q tools/check_env_example.py                                       → exit 0
python tools/check_env_example.py --help                                       → typer-formatted help
python tools/check_env_example.py --strict                                     → exit 1 (extras exist)
pytest tests/unit/tools/test_w6_p1_8_phase3_check_env_example_typer.py        → 8 passed
ruff check --select F401,F841,F811,E9 tools/check_env_example.py               → All checks passed!
```

## Связанные изменения

* **`tools/check_env_example.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_phase3_check_env_example_typer.py`** — новый (8 тестов).
* **`docs/adr/0322-w6-p1-8-phase3-check-env-example-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0322 зарегистрирован (115 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084 (typer preference), ADR-0318 (Phase 1),
ADR-0319 (Phase 2), cycle 153.
