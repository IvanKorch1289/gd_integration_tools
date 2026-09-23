"""CI-gate: проверка Pydantic Settings на unsafe secret defaults.

Контекст
--------
Стратегический анализ 2026-09-22 выявил gap: "Secret не имеет небезопасного
default" (раздел Configuration matrix). Этот gate закрывает его для
Pydantic Settings в ``src/backend/core/config/``.

Что считается unsafe
--------------------

**HIGH severity** (exit 1):
    - Поле типа ``SecretStr`` / ``SecretBytes`` с ``default=SecretStr(<non-empty>)``
      где <non-empty> не пустая строка.
    - Поле типа ``str`` (НЕ SecretStr) с default, который выглядит как реальный
      placeholder: ``changeme``, ``password``, ``secret``, ``admin``, ``test``,
      ``demo``, ``your-key-here``, ``<...>``, ``xxx`` и подобные.

**MEDIUM severity** (warning, exit 0):
    - Поле типа ``SecretStr`` с ``default=SecretStr("")`` — пустая строка
      вместо ``None`` (code smell, но не security issue).

**LOW severity** (info, exit 0):
    - ``str`` поле с default="" и именем, похожим на secret — рекомендация
      перейти на SecretStr/None.

Использование
-------------

::

    python tools/checks/check_unsafe_defaults.py
    python tools/checks/check_unsafe_defaults.py --strict   # fail на MEDIUM
    python tools/checks/check_unsafe_defaults.py --json     # machine-readable

Выходные коды:
    0 — нет HIGH violations;
    1 — есть HIGH violations или (с --strict) MEDIUM.

MINIMAX W11 P0-2 (cycle 157): закрывает configuration matrix gap из
strategic analysis (2026-09-22). ADR-0335.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "src" / "backend" / "core" / "config"

# Имена полей, которые считаются секретами (case-insensitive).
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

# Placeholder values, которые указывают на реальный hardcoded secret
# (а не на пустой default как маркер "не задан").
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^changeme\b", re.IGNORECASE),
    re.compile(r"^password\d*$", re.IGNORECASE),
    re.compile(r"^secret\d*$", re.IGNORECASE),
    re.compile(r"^admin\d*$", re.IGNORECASE),
    re.compile(r"^test\d*$", re.IGNORECASE),
    re.compile(r"^demo\d*$", re.IGNORECASE),
    re.compile(r"^xxx+$", re.IGNORECASE),
    re.compile(r"^your[-_][\w-]+", re.IGNORECASE),
    re.compile(r"^<[^>]+>$", re.IGNORECASE),  # <your-key-here>
    re.compile(r"^placeholder$", re.IGNORECASE),
    re.compile(r"^todo\b", re.IGNORECASE),
    re.compile(r"^fixme\b", re.IGNORECASE),
)


app = typer.Typer(
    name="check-unsafe-defaults",
    help="Проверка Pydantic Settings на unsafe secret defaults.",
    add_completion=False,
)
_console = Console(stderr=True)


def _is_secret_field_name(name: str) -> bool:
    """Эвристика: похоже ли имя поля на секрет."""
    lower = name.lower()
    if lower in _SECRET_FIELD_NAMES:
        return True
    # Также ловим варианты с суффиксами: api_key_v2, password_hash (исключение)
    for secret_name in _SECRET_FIELD_NAMES:
        if lower == secret_name or lower.endswith(f"_{secret_name}"):
            return True
    return False


def _extract_string_value(node: ast.AST) -> str | None:
    """Извлекает строковое значение из AST-узла (если это Constant str или Call SecretStr('...'))."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call):
        # SecretStr("...") или SecretStr()
        func = node.func
        func_name = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        if func_name in {"SecretStr", "SecretBytes"} and node.args:
            return _extract_string_value(node.args[0])
    return None


def _get_field_default(node: ast.AnnAssign) -> tuple[str | None, bool]:
    """Возвращает (default_value_or_None, is_required).

    is_required = True если default отсутствует или Ellipsis (Field(...)).
    """
    if node.value is None:
        return (None, True)
    if isinstance(node.value, ast.Call):
        # Field(default=..., ...) — ищем keyword default
        for kw in node.value.keywords:
            if kw.arg == "default":
                val = _extract_string_value(kw.value)
                return (val, False)
        # Field(...) без default = required (или positional default)
        if node.value.args:
            val = _extract_string_value(node.value.args[0])
            return (val, False)
        # Field() без default и без args → значит default не задан явно
        return (None, True)
    if isinstance(node.value, ast.Constant):
        # x: str = "value"
        if node.value.value is ...:
            return (None, True)
        return (_extract_string_value(node.value), False)
    if isinstance(node.value, ast.Name) and node.value.id == "None":
        return (None, False)
    return (None, False)


def _get_field_type_name(node: ast.AnnAssign) -> str:
    """Возвращает строковое представление типа поля."""
    ann = node.annotation
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        # str | None → str
        left = ann.left
        if isinstance(left, ast.Name):
            return left.id
        if isinstance(left, ast.Attribute):
            return left.attr
    return ""


def _is_secret_type(type_name: str) -> bool:
    return type_name in {"SecretStr", "SecretBytes"}


def _is_placeholder(value: str) -> bool:
    return any(p.match(value) for p in _PLACEHOLDER_PATTERNS)


def _safe_relative(path: Path) -> str:
    """Возвращает path относительно PROJECT_ROOT, или абсолютный путь если вне репо."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def scan_settings_file(path: Path) -> list[dict[str, object]]:
    """Сканирует один Python-файл на unsafe defaults.

    Возвращает список violations: {file, class, field, severity, value, type, message}.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    violations: list[dict[str, object]] = []
    rel_path = _safe_relative(path)

    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        # Только Settings-классы: либо BaseSettings* в bases, либо имя совпадает
        # с шаблоном (XxxSettings / XxxConfig), но НЕ начинается с "Not".
        class_name = cls.name
        bases = {
            b.id if isinstance(b, ast.Name)
            else b.attr if isinstance(b, ast.Attribute)
            else ""
            for b in cls.bases
        }
        has_settings_base = any("Settings" in b for b in bases if b)
        has_settings_suffix = (
            class_name not in {"NotSettings"}
            and not class_name.startswith("Not")
            and (
                class_name.endswith("Settings")
                or class_name.endswith("Config")
            )
        )
        is_settings = has_settings_base or has_settings_suffix
        if not is_settings:
            continue

        for item in cls.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not isinstance(item.target, ast.Name):
                continue
            field_name = item.target.id
            type_name = _get_field_type_name(item)
            default_value, is_required = _get_field_default(item)

            # HIGH: SecretStr/SecretBytes с non-empty non-None default
            if _is_secret_type(type_name) and default_value is not None and default_value != "":
                violations.append({
                    "file": rel_path,
                    "class": class_name,
                    "field": field_name,
                    "severity": "HIGH",
                    "type": type_name,
                    "value": default_value,
                    "message": (
                        f"{type_name} поле '{field_name}' имеет непустой default "
                        f"(value={default_value!r}); используйте default=None или required Field(...)"
                    ),
                })
                continue

            # MEDIUM: SecretStr с default="" (code smell, рекомендация None)
            if _is_secret_type(type_name) and default_value == "":
                violations.append({
                    "file": rel_path,
                    "class": class_name,
                    "field": field_name,
                    "severity": "MEDIUM",
                    "type": type_name,
                    "value": "",
                    "message": (
                        f"{type_name} поле '{field_name}' имеет default='' (code smell); "
                        f"рекомендуется default=None"
                    ),
                })
                continue

            # HIGH: str поле с placeholder default (только если поле называется как секрет)
            if (
                _is_secret_field_name(field_name)
                and type_name == "str"
                and default_value is not None
                and default_value != ""
                and _is_placeholder(default_value)
            ):
                violations.append({
                    "file": rel_path,
                    "class": class_name,
                    "field": field_name,
                    "severity": "HIGH",
                    "type": type_name,
                    "value": default_value,
                    "message": (
                        f"str поле '{field_name}' имеет placeholder default "
                        f"(value={default_value!r}); используйте SecretStr или default=None"
                    ),
                })
                continue

            # LOW: str поле с default="" и именем как секрет — рекомендация SecretStr/None
            if (
                _is_secret_field_name(field_name)
                and type_name == "str"
                and default_value == ""
            ):
                violations.append({
                    "file": rel_path,
                    "class": class_name,
                    "field": field_name,
                    "severity": "LOW",
                    "type": type_name,
                    "value": "",
                    "message": (
                        f"str поле '{field_name}' имеет default=''; рекомендуется "
                        f"SecretStr | None = None для явного маркера 'не задан'"
                    ),
                })

    return violations


def scan_all_settings() -> list[dict[str, object]]:
    """Сканирует все Settings в ``src/backend/core/config/``."""
    if not CONFIG_DIR.exists():
        return []
    all_violations: list[dict[str, object]] = []
    for path in CONFIG_DIR.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        all_violations.extend(scan_settings_file(path))
    return all_violations


def _render_table(violations: list[dict[str, object]]) -> None:
    """Выводит violations в rich-таблице."""
    if not violations:
        _console.print(
            "[green][check-unsafe-defaults][/] OK: "
            "не найдено unsafe secret defaults в Pydantic Settings."
        )
        return

    table = Table(
        title=f"Найдено {len(violations)} potential issue(s)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Sev", style="bold")
    table.add_column("File")
    table.add_column("Class")
    table.add_column("Field")
    table.add_column("Type")
    table.add_column("Value")

    sev_colors = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "blue"}
    for v in violations:
        sev = str(v["severity"])
        color = sev_colors.get(sev, "white")
        table.add_row(
            f"[{color}]{sev}[/]",
            str(v["file"]),
            str(v["class"]),
            str(v["field"]),
            str(v["type"]),
            repr(v["value"])[:40],
        )
    _console.print(table)


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Также fail на MEDIUM violations.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Вывести violations в JSON формате.",
    ),
) -> None:
    """Configuration matrix gate: проверка unsafe secret defaults."""
    if ctx.invoked_subcommand is not None:
        return

    violations = scan_all_settings()
    high = [v for v in violations if v["severity"] == "HIGH"]
    medium = [v for v in violations if v["severity"] == "MEDIUM"]
    low = [v for v in violations if v["severity"] == "LOW"]

    if as_json:
        payload = {
            "total": len(violations),
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
            "violations": violations,
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        _render_table(violations)

    rc = 1 if high else (1 if strict and medium else 0)
    raise typer.Exit(code=rc)


def main(argv: list[str] | None = None) -> int:
    """Backward-compat shim (CLI entry)."""
    if argv is not None:
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
