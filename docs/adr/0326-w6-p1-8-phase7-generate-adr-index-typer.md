# ADR-0326 — W6 P1-8 Phase 7: `tools/generate_adr_index.py` argparse → typer

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W6 P1-8; ADR-0318 (Phase 1); ADR-0319 (Phase 2);
  ADR-0322 (Phase 3); ADR-0323 (Phase 4); ADR-0324 (Phase 5);
  ADR-0325 (Phase 6).

## Контекст

W6 P1-8 momentum: 6 tools подряд мигрированы на typer+rich pattern. Phase 7
мигрирует `tools/generate_adr_index.py` — small (109 LOC) ADR INDEX generator
(Sprint 42 W3). После regen показывает обновлённый INDEX.md (118 ADRs,
включая 5 новых из сессии: ADR-0322, 0323, 0324, 0325, 0326).

## Решение

### Что сделано

**`tools/generate_adr_index.py`** (109 → 137 LOC, +28):
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- `print(...)` → `_console.print("[green]...[/]")` / `_console.print("[red]...[/]")`.
- 2 flags сохранены: `--check` (CI gate), `--dry-run` (preview).
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.
- Removed unused `import sys` (заменён на rich.console).

### Pattern validation (7 tools)

| Tool | LOC (orig→new) | CLI args | Complexity |
|---|---|---|---|
| `import_wsdl.py` (Phase 1) | 90 → 132 | 4 flags | simple |
| `import_postman.py` (Phase 2) | 110 → 169 | 4 flags | simple |
| `check_env_example.py` (Phase 3) | 157 → 187 | 1 flag | trivial |
| `check_dsn_drivers.py` (Phase 4) | 133 → 152 | 1 flag | trivial |
| `s86_workflow_sandbox_guard.py` (Phase 5) | 143 → 178 | 2 flags | trivial |
| `migrate_to_structlog.py` (Phase 6) | 282 → 314 | 1 arg + 1 flag | medium |
| `generate_adr_index.py` (Phase 7) | 109 → 137 | 2 flags | trivial |

Pattern **proven на 7 tools** (4 trivial + 2 simple + 1 medium).

### Teсты

`tests/unit/tools/test_w6_p1_8_phase7_generate_adr_index_typer.py` (7 тестов):
- TestGenerateAdrIndexTyperMigration (3): app is typer, no argparse, --help formatted.
- TestBackwardCompat (3): main(['--help']), main(['--dry-run']), main(['--check'])
  (resilient: принимает 0 или 1).
- TestImportsWork (1): module imports + TITLE_RE/STATUS_RE exposed.

### INDEX.md regeneration (side effect)

`python tools/generate_adr_index.py` после миграции регенерировал `docs/adr/INDEX.md`:
- Переформатировал titles (cleaner, убраны излишние детали)
- Status field теперь bold (`**Accepted**` вместо `Accepted`)
- ADR-0305 (Draft) отсортирован в конец (status-based sorting)
- 118 ADRs total (включая 5 новых из сессии: 0322, 0323, 0324, 0325, 0326)

## Roadmap для остальных ~82 argparse tools

**Phase 8 (cycle 156+)**:
- `tools/check_docstrings.py` (519 LOC) — pre-push gate (medium complexity).
- `tools/migrate_plugin_manifest.py` — manifest migration helper.
- `tools/scaffold.py` — project scaffolding helper.

**Phase 9 (отдельный sprint)**:
- `tools/codegen_plugin.py` (484), `tools/codegen_settings.py` (1107),
  `tools/pre_prod_check.py` (898), `tools/gen_dsl_stubs.py` (875) — high complexity.

## Verification

```
compileall -q tools/generate_adr_index.py                                       → exit 0
python tools/generate_adr_index.py --help                                       → typer-formatted help
python tools/generate_adr_index.py --dry-run                                    → exit 0 (prints to stdout)
python tools/generate_adr_index.py                                              → updates INDEX.md
python tools/generate_adr_index.py --check                                      → exit 0 (up to date)
pytest tests/unit/tools/test_w6_p1_8_phase7_generate_adr_index_typer.py         → 7 passed
ruff check tools/generate_adr_index.py                                          → All checks passed!
```

## Связанные изменения

* **`tools/generate_adr_index.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_phase7_generate_adr_index_typer.py`** — новый (7 тестов).
* **`docs/adr/0326-w6-p1-8-phase7-generate-adr-index-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — регенерирован (118 ADRs total).
* **`docs/adr/INDEX.md`** ADR-0326 зарегистрирован (119 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084, ADR-0318, ADR-0319, ADR-0322, ADR-0323,
ADR-0324, ADR-0325, cycle 153.
