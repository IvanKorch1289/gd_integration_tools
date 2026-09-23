# ADR-0323 — W6 P1-8 Phase 4: `tools/check_dsn_drivers.py` argparse → typer

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W6 P1-8; ADR-0318 (Phase 1); ADR-0319 (Phase 2);
  ADR-0322 (Phase 3 `tools/check_env_example.py`).

## Контекст

ADR-0318 → ADR-0319 → ADR-0322 применили proven typer+rich pattern к 3 tools
разной complexity (4-flag, 4-flag, 1-flag). Pattern validated, готов к
тиражированию.

ADR-0319 Phase 4 roadmap (cycle 156+):
1. `tools/check_dsn_drivers.py` (133 LOC) — простой проверка DSN.
2. `tools/discover_plugin_capabilities.py` (241 LOC) — частично typer.

Cycle 153 ещё не достиг cycle 156, но momentum pattern proven, продолжаем
с Phase 4 (1-flag DSN check tool).

## Решение

### Что сделано

**`tools/check_dsn_drivers.py`** (133 → 152 LOC, +19):
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- `print(render_human(results))` → `_console.print(render_human(results))` (rich).
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.
- Removed unused `import sys` (используется только через `SystemExit`).

### Pattern validation (4 tools)

| Tool | LOC (orig→new) | CLI args | Complexity |
|---|---|---|---|
| `import_wsdl.py` (Phase 1) | 90 → 132 | `--url, --connector, --write, --output-dir` | simple |
| `import_postman.py` (Phase 2) | 110 → 169 | `--file, --connector, --write, --output-dir` | simple |
| `check_env_example.py` (Phase 3) | 157 → 187 | `--strict` | trivial |
| `check_dsn_drivers.py` (Phase 4) | 133 → 152 | `--ci` | trivial |

Pattern **proven на 4 tools** (2 simple + 2 trivial). Готов к тиражированию.

### Тесты

`tests/unit/tools/test_w6_p1_8_phase4_check_dsn_drivers_typer.py` (7 тестов):
- TestCheckDsnDriversTyperMigration (3): app is typer, no argparse,
  typer-formatted --help.
- TestBackwardCompat (3): main(['--help']), main([]), main(['--ci']).
- TestImportsWork (1): module imports work + DSN_DRIVER_MAP exposed.

## Roadmap для остальных ~84 argparse tools

**Phase 5 (cycle 156+)**:
1. `tools/discover_plugin_capabilities.py` (241 LOC) — частично typer (S62 W3).
2. `tools/codegen_plugin.py` (484 LOC) — medium complexity.
3. `tools/check_docstrings.py` (519 LOC) — medium complexity.

**Phase 6 (отдельный sprint)**:
- `tools/codegen_settings.py` (1107), `tools/pre_prod_check.py` (898),
  `tools/gen_dsl_stubs.py` (875) — high complexity.

## Альтернативы (отклонённые)

* **Batch commit для всех Phase 4-5 tools**: отклонено — большой diff, трудно review.
* **Skip Phase 4 до cycle 156**: отклонено — momentum pattern proven,
  каждый tool = atomic commit per CLAUDE.md invariants.

## Verification

```
compileall -q tools/check_dsn_drivers.py                                       → exit 0
python tools/check_dsn_drivers.py --help                                       → typer-formatted help
python tools/check_dsn_drivers.py --ci                                         → exit 1 (missing drivers)
pytest tests/unit/tools/test_w6_p1_8_phase4_check_dsn_drivers_typer.py        → 7 passed
ruff check --select F401,F841,F811,E9 tools/check_dsn_drivers.py                → All checks passed!
```

## Связанные изменения

* **`tools/check_dsn_drivers.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_phase4_check_dsn_drivers_typer.py`** — новый (7 тестов).
* **`docs/adr/0323-w6-p1-8-phase4-check-dsn-drivers-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0323 зарегистрирован (116 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084, ADR-0318, ADR-0319, ADR-0322, cycle 153.
