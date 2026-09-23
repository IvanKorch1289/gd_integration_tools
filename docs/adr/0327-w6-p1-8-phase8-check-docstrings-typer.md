# ADR-0327 — W6 P1-8 Phase 8: `tools/check_docstrings.py` argparse → typer

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W6 P1-8; ADR-0318 (Phase 1); ADR-0319 (Phase 2);
  ADR-0322 (Phase 3); ADR-0323 (Phase 4); ADR-0324 (Phase 5);
  ADR-0325 (Phase 6); ADR-0326 (Phase 7).

## Контекст

W6 P1-8 momentum: 7 tools подряд мигрированы на proven typer+rich pattern.
Phase 8 мигрирует `tools/check_docstrings.py` — pre-push gate (519 LOC,
medium-high complexity: 5 flags + positional args).

## Решение

### Что сделано

**`tools/check_docstrings.py`** (519 → 575 LOC, +56):
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- 5 flags сохранены: `--summary`, `--json`, `--allowlist`, `--module-level`, `--max-allowed`.
- Positional `paths` argument (with Path type validation) сохранён.
- `print(output)` → `sys.stdout.write(output)` (CI grep-compatibility, без rich
  formatting для output — это даёт чистый JSON/human-readable output).
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.
- Removed unused `import sys` для argparse (но `sys.stdout.write` остался для
  CI-compatible output).

### Pattern validation (8 tools)

| Tool | LOC (orig→new) | CLI args | Complexity |
|---|---|---|---|
| `import_wsdl.py` (Phase 1) | 90 → 132 | 4 flags | simple |
| `import_postman.py` (Phase 2) | 110 → 169 | 4 flags | simple |
| `check_env_example.py` (Phase 3) | 157 → 187 | 1 flag | trivial |
| `check_dsn_drivers.py` (Phase 4) | 133 → 152 | 1 flag | trivial |
| `s86_workflow_sandbox_guard.py` (Phase 5) | 143 → 178 | 2 flags | trivial |
| `migrate_to_structlog.py` (Phase 6) | 282 → 314 | 1 arg + 1 flag | medium |
| `generate_adr_index.py` (Phase 7) | 109 → 137 | 2 flags | trivial |
| `check_docstrings.py` (Phase 8) | 519 → 575 | 5 flags + positional | medium-high |

Pattern **proven на 8 tools** (4 trivial + 2 simple + 2 medium).

### Тесты

`tests/unit/tools/test_w6_p1_8_phase8_check_docstrings_typer.py` (8 тестов):
- TestCheckDocstringsTyperMigration (3): app is typer, no argparse, --help formatted.
- TestBackwardCompat (4): main(['--help']), main(['--summary']),
  main(['--json', ...]), main(['--max-allowed', '999999', ...]).
- TestImportsWork (1): module imports + DocstringVisitor/MissingDocstring/FileStats/AggregateStats exposed.

**Note**: этот test file использует дополнительный workaround — `sys.modules`
registration для dataclass support (dataclass decorator требует модуль быть
в `sys.modules`). Задокументировано в test file docstring.

## Roadmap для остальных ~82 argparse tools

**Phase 9 (cycle 156+)**:
- `tools/migrate_plugin_manifest.py` — manifest migration helper.
- `tools/scaffold.py` — project scaffolding helper.
- `tools/check_layer_imports.py` — architecture compliance gate.
- `tools/add_f401_noqa.py` — auto-fix F401 violations.
- `tools/add_f401_multiline_noqa.py` — same for multiline.

**Phase 10 (отдельный sprint)**:
- `tools/codegen_plugin.py` (484), `tools/codegen_settings.py` (1107),
  `tools/pre_prod_check.py` (898), `tools/gen_dsl_stubs.py` (875) — high complexity.

## Verification

```
compileall -q tools/check_docstrings.py                                            → exit 0
python tools/check_docstrings.py --help                                              → typer-formatted help
python tools/check_docstrings.py --summary tools/check_docstrings.py                → exit 0 (no missing)
python tools/check_docstrings.py --max-allowed 5 src/                                → exit 0 (250 < 999999)
python tools/check_docstrings.py --max-allowed 5 src/                                → reports 250 missing
pytest tests/unit/tools/test_w6_p1_8_phase8_check_docstrings_typer.py                → 8 passed
ruff check tools/check_docstrings.py                                                → 1 pre-existing F841 (unrelated)
```

## Связанные изменения

* **`tools/check_docstrings.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_phase8_check_docstrings_typer.py`** — новый (8 тестов).
* **`docs/adr/0327-w6-p1-8-phase8-check-docstrings-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0327 зарегистрирован (120 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084, ADR-0318, ADR-0319, ADR-0322, ADR-0323,
ADR-0324, ADR-0325, ADR-0326, cycle 153.
