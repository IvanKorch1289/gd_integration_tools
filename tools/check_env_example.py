"""Wave F.9 (опционально): проверка покрытия .env.example.

Скрипт проходит по всем Pydantic Settings в ``src/core/config/`` и
выясняет ожидаемые env-переменные (``<prefix>_<field>``). Затем
сверяет с реальным ``.env.example`` — список missing/extra переменных.

Поведение:

* Exit 0 — всё покрыто.
* Exit 1 — есть переменные в Settings, не описанные в .env.example
  (warning-level: добавьте описание).
* ``--strict`` — exit 1 ещё и если в .env.example есть лишние
  переменные, не используемые в Settings.

Использование:

  python tools/check_env_example.py
  python tools/check_env_example.py --strict

MINIMAX W6 P1-8 Phase 3 (cycle 153): мигрирован с ``argparse`` на ``typer`` +
``rich`` (libraries > custom, per ADR-0084). Сохранены: typer-native entry +
legacy ``main()`` callback для backward-compat с pre-existing scripts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import typer
from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "src" / "core" / "config"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

app = typer.Typer(
    name="check-env-example",
    help="Проверка покрытия .env.example относительно Pydantic Settings.",
    add_completion=False,
)
_console = Console(stderr=True)


def _base_name(node: ast.AST) -> str:
    """Возвращает имя base-класса (без generic'ов и qualifiers)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _extract_env_prefixes_from_file(path: Path) -> list[tuple[str, list[str]]]:
    """Возвращает список ``(env_prefix, field_names)`` для каждого Settings-класса.

    Парсит AST, ищет:
      * Класс с base ``BaseSettings`` / ``BaseSettingsWithLoader``.
      * Внутри — ``model_config = SettingsConfigDict(env_prefix=..., ...)``.
      * И поля-аннотации (``foo: int = ...``).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []

    out: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {_base_name(b) for b in node.bases}
        if not ({"BaseSettings", "BaseSettingsWithLoader"} & bases):
            continue

        prefix = ""
        field_names: list[str] = []
        for item in node.body:
            if isinstance(item, ast.Assign):
                for tgt in item.targets:
                    if (
                        isinstance(tgt, ast.Name)
                        and tgt.id == "model_config"
                        and isinstance(item.value, ast.Call)
                    ):
                        for kw in item.value.keywords:
                            if (
                                kw.arg == "env_prefix"
                                and isinstance(kw.value, ast.Constant)
                                and isinstance(kw.value.value, str)
                            ):
                                prefix = kw.value.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_names.append(item.target.id)

        if prefix and field_names:
            out.append((prefix, field_names))

    return out


def collect_expected_env_vars() -> set[str]:
    """Собирает ожидаемые env-переменные из всех Pydantic Settings."""
    expected: set[str] = set()
    for path in CONFIG_DIR.rglob("*.py"):
        for prefix, fields in _extract_env_prefixes_from_file(path):
            for field in fields:
                expected.add(f"{prefix}_{field}".upper())
    return expected


def collect_env_example_vars() -> set[str]:
    """Парсит ``.env.example`` и возвращает множество описанных переменных."""
    if not ENV_EXAMPLE.exists():
        return set()
    documented: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        documented.add(name)
    return documented


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Также fail при наличии лишних переменных в .env.example.",
    ),
) -> None:
    """Wave F.9: проверка покрытия .env.example."""
    if ctx.invoked_subcommand is not None:
        return

    expected = collect_expected_env_vars()
    documented = collect_env_example_vars()

    missing = sorted(expected - documented)
    extra = sorted(documented - expected)

    rc = 0
    if missing:
        _console.print(
            f"[red][check-env-example][/] {len(missing)} переменных Settings не описаны в .env.example:"
        )
        for v in missing:
            _console.print(f"  - {v}")
        rc = 1
    if extra:
        _console.print(
            f"[yellow][check-env-example][/] {len(extra)} переменных в .env.example не используются в Settings:"
        )
        for v in extra:
            _console.print(f"  - {v}")
        if strict:
            rc = 1
    if rc == 0:
        _console.print(
            f"[green][check-env-example][/] OK: {len(expected)} переменных, .env.example покрывает все."
        )
    raise typer.Exit(code=rc)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI (backward-compat shim).

    Запускает typer app через typer.testing.CliRunner (для тестов)
    или sys.argv (для CLI invocation). Возвращает exit code.
    """
    if argv is not None:
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    # CLI invocation: typer сам подхватит sys.argv[1:]
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
