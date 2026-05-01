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
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "src" / "core" / "config"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


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
        if not bases & {"BaseSettings", "BaseSettingsWithLoader"}:
            continue

        env_prefix = ""
        field_names: list[str] = []
        for item in node.body:
            if isinstance(item, ast.Assign):
                if any(
                    isinstance(t, ast.Name) and t.id == "model_config" for t in item.targets
                ):
                    env_prefix = _extract_env_prefix(item.value)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fname = item.target.id
                if not fname.startswith("_") and fname != "yaml_group":
                    field_names.append(fname)
        out.append((env_prefix, field_names))
    return out


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _extract_env_prefix(call: ast.expr) -> str:
    if not isinstance(call, ast.Call):
        return ""
    for kw in call.keywords:
        if kw.arg == "env_prefix" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return ""


def collect_expected_env_vars() -> set[str]:
    """Собрать все ожидаемые env-переменные из Settings."""
    expected: set[str] = set()
    for path in CONFIG_DIR.rglob("*.py"):
        for prefix, fields in _extract_env_prefixes_from_file(path):
            for field in fields:
                # Pydantic env case: <PREFIX><FIELD_UPPER>.
                expected.add(f"{prefix}{field.upper()}")
    return expected


def collect_env_example_vars() -> set[str]:
    """Парсит .env.example — собирает имена переменных."""
    if not ENV_EXAMPLE.exists():
        return set()
    out: set[str] = set()
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            out.add(line.split("=", 1)[0].strip())
    return out


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Также fail при наличии лишних переменных в .env.example.",
    )
    args = parser.parse_args(argv)

    expected = collect_expected_env_vars()
    documented = collect_env_example_vars()

    missing = sorted(expected - documented)
    extra = sorted(documented - expected)

    rc = 0
    if missing:
        print(
            f"[check_env_example] {len(missing)} переменных Settings не описаны в .env.example:",
            file=sys.stderr,
        )
        for v in missing:
            print(f"  - {v}")
        rc = 1
    if extra:
        msg = (
            f"[check_env_example] {len(extra)} переменных в .env.example "
            "не используются в Settings:"
        )
        print(msg, file=sys.stderr)
        for v in extra:
            print(f"  - {v}")
        if args.strict:
            rc = 1
    if rc == 0:
        print(
            f"[check_env_example] OK: {len(expected)} переменных, .env.example покрывает все.",
            file=sys.stderr,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
