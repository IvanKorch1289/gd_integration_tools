# ADR-0332 — W6 P1-8 Phase 9: `tools/add_f401_multiline_noqa.py` argparse → typer

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W6 P1-8; ADR-0318 (Phase 1); ADR-0319 (Phase 2);
  ADR-0322 (Phase 3); ADR-0323 (Phase 4); ADR-0324 (Phase 5);
  ADR-0325 (Phase 6); ADR-0326 (Phase 7); ADR-0327 (Phase 8).

## Контекст

W6 P1-8 momentum продолжается: 8 tools подряд мигрированы на proven
typer+rich pattern. Phase 9 мигрирует `tools/add_f401_multiline_noqa.py`
(D-AUDIT-3024 cycle-49, F401 silence для multi-line imports) — small
(102 LOC) auto-fix tool.

## Решение

### Что сделано

**`tools/add_f401_multiline_noqa.py`** (102 → 113 LOC, +11):
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- `print(...)` → `_console.print("[green]Updated[/] ...")` (rich color codes).
- 2 flags сохранены: `--root`, `--verbose`.
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` + `app()` fallback.

### Pattern validation (9 tools)

| Tool | LOC (orig→new) | Args | Complexity |
|---|---|---|---|
| Phase 1-8 (8 tools) | various | various | various |
| `add_f401_multiline_noqa.py` (Phase 9) | 102 → 113 | 2 flags | trivial |

Pattern **proven на 9 tools**. Pattern полностью reproducible.

### Тесты

`tests/unit/tools/test_w6_p1_8_phase9_add_f401_multiline_noqa_typer.py` (7 тестов):
- TestAddF401MultilineNoqaTyperMigration (3): app is typer, no argparse, --help formatted.
- TestBackwardCompat (3): main(['--help']), main([]), main(['--root', '<dir>']).
- TestImportsWork (1): module imports + _process_file exposed.

## Verification

```
compileall -q tools/add_f401_multiline_noqa.py                                         → exit 0
python tools/add_f401_multiline_noqa.py --help                                         → typer-formatted help
python tools/add_f401_multiline_noqa.py --root tools/add_f401_multiline_noqa.py         → exit 0 (no changes)
pytest tests/unit/tools/test_w6_p1_8_phase9_*_typer.py                                   → 7 passed
ruff check tools/add_f401_multiline_noqa.py                                              → 1 pre-existing F841 (unrelated)
```

## Связанные изменения

* **`tools/add_f401_multiline_noqa.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_phase9_add_f401_multiline_noqa_typer.py`** — новый (7 тестов).
* **`docs/adr/0332-w6-p1-8-phase9-add-f401-multiline-noqa-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0332 зарегистрирован (125 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084, ADR-0318-ADR-0327 (Phases 1-8), cycle 153.
