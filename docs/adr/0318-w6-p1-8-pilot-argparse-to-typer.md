# ADR-0318 — W6 P1-8: argparse → typer CLI migration pilot (tools/import_wsdl.py)

* Статус: **Accepted** (cycle 152).
* Связано с: MINIMAX W6 P1-8 (typer+rich CLI per ADR-0084).
* Pilot для ~90 argparse tools в проекте.

## Контекст

Cycle 152 W6 P1-8 recon:

* **Уже typer+rich**: `tools/cli.py` (392 LOC, 4 sub-commands: route/workflow/cache/agent)
  + 8+ tools (`dsl_diff.py`, `discover_plugin_capabilities.py`,
  `codegen_service.py`, `check_layer_imports.py` и т.д. — S62 W3 миграция).
* **argparse tools**: ~90 файлов (включая `import_postman.py`,
  `import_wsdl.py`, `codegen_settings.py` 1107 LOC,
  `pre_prod_check.py` 898 LOC, `gen_dsl_stubs.py` 875 LOC).
* **MINIMAX baseline**: "моно-manage.py (1838 LOC)" — не существует.
  MINIMAX baseline был преувеличением. W6 P1-8 частично уже выполнен
  (S62 W3 + Sprint 35 для `tools/cli.py`).

**Решение**: incremental migration по 1-2 tools за wave. Pilot: `tools/import_wsdl.py`
(90 LOC, простой argparse).

## Решение (Pilot)

### Что сделано

**`tools/import_wsdl.py`** (90 → 132 LOC, +42):
- Аргументы: `--url`, `--connector`, `--write`, `--output-dir`.
- `argparse.ArgumentParser` → `typer.Typer` + `@app.callback(invoke_without_command=True)`.
- `sys.stdout.write(f"[...]")` → `_console.print(f"[bold cyan][import-wsdl][/] ...")`
  (rich formatting).
- Backward-compat `main(argv=None)` через `CliRunner.invoke()` +
  `app()` для sys.argv fallback.

### Pattern (для будущих migrations)

```python
app = typer.Typer(
    name="tool-name",
    help="Tool description.",
    no_args_is_help=True,
    add_completion=False,
)
_console = Console()


@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    required_arg: Optional[str] = typer.Option(None, "--required-arg"),
    ...
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if required_arg is None:
        _console.print("[bold red]Error:[/] --required-arg обязателен")
        raise typer.Exit(code=2)
    _run_main(...)


def _run_main(...) -> None:
    # основная логика — extract из argparse main()
    ...


if __name__ == "__main__":
    raise SystemExit(main())
```

**Preserves backward-compat**:
- `main(argv=None)` — CliRunner для тестов с явным argv.
- `main()` без args — `app()` который использует sys.argv.
- Public API: `app`, `main`, `_collect_operations` (для импорта из других tools).

### Тесты

`tests/unit/tools/test_w6_p1_8_import_wsdl_typer.py` (8 тестов):
- TestImportWsdlTyperMigration (4): app is typer, --help formatted, missing args,
  no argparse import.
- TestBackwardCompat (3): main([--help]) → 0, main([]) → 0, main() → 0.
- TestImportsWork (1): module imports work.

## Roadmap для остальных ~89 argparse tools

**Phase 2** (отдельные waves, ~cycle 156+):
1. **Маленькие** (< 200 LOC, простые CLI): `import_postman.py` (110),
   `check_env_example.py` (157), `check_dsn_drivers.py` (133) — по 1 за wave.
2. **Средние** (200-500 LOC): `codegen_plugin.py` (484), `check_docstrings.py`
   (519), `discover_plugin_capabilities.py` (241, частично typer).
3. **Большие** (500+ LOC): `codegen_settings.py` (1107),
   `pre_prod_check.py` (898), `gen_dsl_stubs.py` (875) — отдельные waves
   с тщательным testing.

**Не мигрировать** (отдельная decision matrix):
- Tools где argparse использует сложные sub-parser hierarchies
  (например, `verify_pypi_versions.py`).
- Tools где backward-compat важен (legacy CI scripts).

## Альтернативы (отклонённые)

* **Mass-migrate все 90 tools в один commit**: отклонено — большой diff,
  трудно review.
* **Replace argparse с click (другая библиотека)**: typer УЖЕ в deps +
  переиспользует click internals — typer==click-native CLI + rich output.
* **Keep argparse навсегда**: отклонено — ADR-0084 explicit preference +
  MINIMAX plan requires typer+rich consolidation.

## Verification (cycle 152)

```
compileall -q tools/import_wsdl.py                           → exit 0
uv run python tools/import_wsdl.py --help                   → typer-formatted help (0 exit)
uv run python tools/import_wsdl.py                          → shows help (no required args)
uv run python -m pytest tests/unit/tools/test_w6_p1_8_import_wsdl_typer.py
  → 8 passed
ruff check --select F401,F841,F811,E9                       → All checks passed!
```

## Связанные изменения

* **`tools/import_wsdl.py`** — мигрирован argparse → typer+rich.
* **`tests/unit/tools/test_w6_p1_8_import_wsdl_typer.py`** — новый (8 тестов).
* **`docs/adr/0318-w6-p1-8-pilot-argparse-to-typer.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0318 зарегистрирован (111 ADRs total).
* **CHANGELOG.md** + **docs/roadmap/PROGRESS_LEDGER.md** — синхронизированы.

Refs: MINIMAX W6 P1-8, ADR-0084 (libraries > custom), Sprint 62 W3,
Sprint 35 (tools/cli.py typer CLI), ADR-0318 (this), cycle 152.