# ADR-0324 — W6 P1-8 Phase 5: `tools/s86_workflow_sandbox_guard.py` argparse → typer

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W6 P1-8; ADR-0318 (Phase 1); ADR-0319 (Phase 2);
  ADR-0322 (Phase 3); ADR-0323 (Phase 4).

## Контекст

W6 P1-8 momentum: ADR-0318/0319/0322/0323 мигрировали 4 tools (import_wsdl,
import_postman, check_env_example, check_dsn_drivers) на proven typer+rich
pattern. Phase 5 продолжает trend с `tools/s86_workflow_sandbox_guard.py`
(S86 — Temporal sandbox static analyzer, 143 LOC).

## Решение

### Что сделано

**`tools/s86_workflow_sandbox_guard.py`** (143 → 178 LOC, +35):
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- `print(..., file=sys.stderr)` → `_console.print("[red]ERROR: ...[/]")` (rich color codes).
- 2 flags сохранены: `--path` (Path argument), `--verbose` (boolean flag).
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.
- Removed unused `import sys` (заменён на rich.console).

### Pattern validation (5 tools)

| Tool | LOC (orig→new) | CLI args | Complexity |
|---|---|---|---|
| `import_wsdl.py` (Phase 1) | 90 → 132 | 4 flags | simple |
| `import_postman.py` (Phase 2) | 110 → 169 | 4 flags | simple |
| `check_env_example.py` (Phase 3) | 157 → 187 | 1 flag | trivial |
| `check_dsn_drivers.py` (Phase 4) | 133 → 152 | 1 flag | trivial |
| `s86_workflow_sandbox_guard.py` (Phase 5) | 143 → 178 | 2 flags | trivial |

Pattern **proven на 5 tools** (3 trivial + 2 simple). Migration predictable.

### Тесты

`tests/unit/tools/test_w6_p1_8_phase5_s86_workflow_sandbox_guard_typer.py` (8 тестов):
- TestS86WorkflowSandboxGuardTyperMigration (3): app is typer, no argparse, --help formatted.
- TestBackwardCompat (4): main(['--help']), main([]), main(['--path', 'nonexistent']),
  main(['--verbose']).
- TestImportsWork (1): module imports + SAFE_PATTERNS/FORBIDDEN_PATTERNS exposed.

## Roadmap для остальных ~83 argparse tools

**Phase 6 (cycle 156+)**:
- `tools/migrate_to_structlog.py` (282 LOC) — auto-migration script.
- `tools/check_docstrings.py` (519 LOC) — pre-push gate (medium complexity).
- `tools/generate_adr_index.py` — ADR generation helper.

**Phase 7 (отдельный sprint)**:
- `tools/codegen_plugin.py` (484), `tools/codegen_settings.py` (1107),
  `tools/pre_prod_check.py` (898), `tools/gen_dsl_stubs.py` (875) — high complexity.

## Verification

```
compileall -q tools/s86_workflow_sandbox_guard.py                                → exit 0
python tools/s86_workflow_sandbox_guard.py --help                                → typer-formatted help
python tools/s86_workflow_sandbox_guard.py                                       → exit 0 (no violations)
pytest tests/unit/tools/test_w6_p1_8_phase5_s86_workflow_sandbox_guard_typer.py → 8 passed
ruff check tools/s86_workflow_sandbox_guard.py                                   → All checks passed!
```

## Связанные изменения

* **`tools/s86_workflow_sandbox_guard.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_phase5_s86_workflow_sandbox_guard_typer.py`** — новый (8 тестов).
* **`docs/adr/0324-w6-p1-8-phase5-s86-workflow-sandbox-guard-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0324 зарегистрирован (117 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084, ADR-0318, ADR-0319, ADR-0322, ADR-0323, cycle 153.
