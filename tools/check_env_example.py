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
CONFIG_DIR = PROJECT_ROOT / "src" / "backend" / "core" / "config"
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


def _extract_env_prefixes_from_file(
    path: Path,
) -> list[tuple[str, list[tuple[str, bool]]]]:
    """Возвращает список ``(env_prefix, [(field_name, is_required), ...])``.

    Парсит AST, ищет:
      * Класс с base ``BaseSettings`` / ``BaseSettingsWithLoader``,
        ИЛИ с ``model_config = SettingsConfigDict(env_prefix=..., ...)``
        (W11 P0-3 fix: ранее ловил только BaseSettings — пропускал 100% Settings
        с inline ``SettingsConfigDict``).
      * Внутри — ``model_config = SettingsConfigDict(env_prefix=..., ...)``.
      * И поля-аннотации (``foo: int = ...``).

    is_required = True если поле без default (``Field(...)`` или ``Field(..., ...)``).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []

    out: list[tuple[str, list[tuple[str, bool]]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        prefix = ""
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

        # Settings detection: env_prefix в model_config ИЛИ BaseSettings в bases
        bases = {_base_name(b) for b in node.bases}
        has_settings_base = bool({"BaseSettings", "BaseSettingsWithLoader"} & bases)
        if not (prefix or has_settings_base):
            continue

        fields: list[tuple[str, bool]] = []
        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not isinstance(item.target, ast.Name):
                continue
            fname = item.target.id
            # Required: нет default, или Field(...) с Ellipsis
            is_required = False
            if item.value is None:
                is_required = True
            elif isinstance(item.value, ast.Call) and isinstance(
                item.value.func, ast.Name
            ):
                if item.value.func.id == "Field":
                    has_default_kw = any(
                        kw.arg in {"default", "default_factory"}
                        for kw in item.value.keywords
                    )
                    # Positional Ellipsis = required
                    has_ellipsis = any(
                        isinstance(arg, ast.Constant) and arg.value is ...
                        for arg in item.value.args
                    )
                    if not has_default_kw and not item.value.args:
                        # Field(description=...) без default = required
                        is_required = True
                    elif has_ellipsis and len(item.value.args) == 1:
                        # Field(...) единственный аргумент = required
                        is_required = True
                    elif has_default_kw or (item.value.args and not has_ellipsis):
                        # Field(default=...) или Field("value", ...) = optional
                        is_required = False
            fields.append((fname, is_required))

        if prefix and fields:
            out.append((prefix, fields))

    return out


def collect_expected_env_vars() -> set[str]:
    """Собирает ожидаемые env-переменные из всех Pydantic Settings."""
    expected: set[str] = set()
    for path in CONFIG_DIR.rglob("*.py"):
        for prefix, fields in _extract_env_prefixes_from_file(path):
            for field, _ in fields:
                expected.add(f"{prefix.rstrip('_')}_{field}".upper())
    return expected


def collect_required_secret_env_vars() -> set[str]:
    """Собирает required env vars с именами, похожими на секреты.

    Эти переменные ОБЯЗАНЫ быть в ``.env.example`` (иначе — bootstrap fallback).
    """
    expected: set[str] = set()
    for path in CONFIG_DIR.rglob("*.py"):
        for prefix, fields in _extract_env_prefixes_from_file(path):
            for field, is_required in fields:
                if is_required and _is_secret_field_name(field):
                    expected.add(f"{prefix.rstrip('_')}_{field}".upper())
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


# Имена полей, которые считаются секретами — те же, что в check_unsafe_defaults.
_SECRET_FIELD_NAMES = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "access_key",
        "token",
        "auth_token",
        "api_token",
        "session_token",
        "client_secret",
        "signature_secret",
        "bind_password",
        "private_key",
        "shared_secret",
        "sentinel_password",
    }
)


def _is_secret_field_name(name: str) -> bool:
    """Эвристика: похоже ли имя поля на секрет."""
    lower = name.lower()
    if lower in _SECRET_FIELD_NAMES:
        return True
    for secret_name in _SECRET_FIELD_NAMES:
        if lower.endswith(f"_{secret_name}"):
            return True
    return False


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Также fail при наличии лишних переменных в .env.example.",
    ),
    matrix: bool = typer.Option(
        False,
        "--matrix",
        help="Расширенная matrix-проверка: required secret vars, unknown vars.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Machine-readable JSON output.",
    ),
) -> None:
    """Wave F.9: проверка покрытия .env.example.

    W11 P0-3: добавлен --matrix для required-secret и unknown-vars проверок.
    """
    if ctx.invoked_subcommand is not None:
        return

    expected = collect_expected_env_vars()
    documented = collect_env_example_vars()

    missing = sorted(expected - documented)
    extra = sorted(documented - expected)

    # W11 P0-3 matrix checks
    matrix_missing_secret: list[str] = []
    if matrix:
        required_secrets = collect_required_secret_env_vars()
        matrix_missing_secret = sorted(required_secrets - documented)

    rc = 0
    if missing:
        # W11 P0-3: project convention — .env.example хранит ТОЛЬКО секреты,
        # остальные vars в config_profiles/{profile}.yml. Default — warning
        # (exit 0), --strict — fail (для проектов, где ВСЁ в .env.example).
        _console.print(
            f"[yellow][check-env-example][/] {len(missing)} переменных Settings не описаны в .env.example "
            f"(могут быть в config_profiles/*.yml — это норма для layered config):"
        )
        for v in missing[:20]:
            _console.print(f"  - {v}")
        if len(missing) > 20:
            _console.print(f"  ... и ещё {len(missing) - 20}")
        if strict:
            rc = 1
    if matrix and matrix_missing_secret:
        # Required secrets обязаны быть в .env.example — иначе bootstrap-fallback.
        _console.print(
            f"[red][check-env-example --matrix][/] "
            f"{len(matrix_missing_secret)} обязательных SECRET-переменных отсутствуют в .env.example "
            f"(риск bootstrap-fallback):"
        )
        for v in matrix_missing_secret[:20]:
            _console.print(f"  - {v}")
        if len(matrix_missing_secret) > 20:
            _console.print(f"  ... и ещё {len(matrix_missing_secret) - 20}")
        rc = 1
    if extra:
        _console.print(
            f"[yellow][check-env-example][/] {len(extra)} переменных в .env.example не используются в Settings:"
        )
        for v in extra[:20]:
            _console.print(f"  - {v}")
        if len(extra) > 20:
            _console.print(f"  ... и ещё {len(extra) - 20}")
        if strict:
            rc = 1

    # JSON output (для CI integration)
    if as_json:
        import json as _json
        import sys as _sys

        payload = {
            "total_expected": len(expected),
            "total_documented": len(documented),
            "missing": missing,
            "extra": extra,
            "matrix_required_secrets_missing": matrix_missing_secret if matrix else [],
        }
        _sys.stdout.write(_json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    elif rc == 0:
        _console.print(
            f"[green][check-env-example][/] OK: {len(expected)} переменных обнаружено, "
            f"{len(documented)} в .env.example, "
            f"{len(extra)} unknown (use --strict для fail)."
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
