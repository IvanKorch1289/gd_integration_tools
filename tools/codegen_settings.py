"""Settings codegen — атомарная генерация Settings-класса (W21.5a).

Создаёт за один проход 5 артефактов по описанию полей:

1. ``src/core/config/services/<name>.py`` — Settings-класс, наследник
   ``BaseSettingsWithLoader`` с указанными ``Field``-полями.
2. Реэкспорт в ``src/core/config/services/__init__.py``.
3. Регистрация в ``src/core/config/settings.py::Settings`` (import +
   атрибут).
4. Секция ``<name>:`` в ``config_profiles/base.yml`` с non-secret
   defaults.
5. ENV-записи ``<ENV_PREFIX><FIELD_UPPER>=`` в ``.env.example``
   (только для secret-полей).

Контракт описания поля::

    name:type:default:visibility[:constraints]

Где:

* ``type ∈ {str, int, float, bool, str|None, int|None}``;
* ``visibility ∈ {secret, non-secret}`` — secret уходит в ``.env.example``,
  non-secret — в ``base.yml`` с указанным default;
* ``constraints`` (optional, через запятую): ``ge=N``, ``le=N``,
  ``min_length=N``, ``max_length=N``, ``pattern=<regex>``.

Запуск::

    python tools/codegen_settings.py new \\
      --name kafka \\
      --env-prefix KAFKA_ \\
      --field bootstrap_servers:str:"localhost:9092":non-secret \\
      --field timeout_ms:int:30000:non-secret \\
      --field username:str:"":secret \\
      --field password:str:"":secret

Все шаги идемпотентны: повторный запуск не дублирует записи. Перед
любой правкой делается резервная копия ``.bak`` рядом с файлом.

Завершается ``exit 1`` при любой ошибке валидации входа или конфликте
имён.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = ROOT / "src" / "core" / "config" / "services"
SETTINGS_FILE = ROOT / "src" / "core" / "config" / "settings.py"
SERVICES_INIT = SERVICES_DIR / "__init__.py"
BASE_YAML = ROOT / "config_profiles" / "base.yml"
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG_AUDIT = ROOT / "tools" / "config_audit.py"

_VALID_TYPES: frozenset[str] = frozenset(
    {"str", "int", "float", "bool", "str|None", "int|None", "float|None"}
)
_VALID_VISIBILITY: frozenset[str] = frozenset({"secret", "non-secret"})
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ENV_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*_$")


@dataclass(slots=True, frozen=True)
class FieldSpec:
    """Описание одного поля Settings-класса."""

    name: str
    type_: str
    default: str
    visibility: str
    constraints: tuple[str, ...] = ()

    @property
    def is_secret(self) -> bool:
        return self.visibility == "secret"

    @property
    def python_default_literal(self) -> str:
        """Литерал default'а в Python-коде Settings-класса."""
        if self.is_secret:
            return "..."
        if "None" in self.type_ and self.default in ("", "None"):
            return "None"
        if self.type_ == "bool":
            return self.default if self.default in ("True", "False") else "False"
        if self.type_ in ("int", "int|None"):
            return self.default or "0"
        if self.type_ in ("float", "float|None"):
            return self.default or "0.0"
        # str / str|None
        return f'"{self.default}"'

    @property
    def yaml_default_literal(self) -> str:
        """Скаляр default'а для записи в base.yml (non-secret only)."""
        if self.type_ == "bool":
            return self.default.lower() if self.default else "false"
        if self.type_ in ("int", "int|None", "float", "float|None"):
            return self.default or "0"
        if "None" in self.type_ and self.default in ("", "None"):
            return "null"
        return self.default if self.default else '""'


_FIELD_RE = re.compile(
    r"^(?P<name>[a-z][a-z0-9_]*):"
    r"(?P<type>str\|None|int\|None|float\|None|str|int|float|bool):"
    r"(?P<default>.*?):"
    r"(?P<visibility>secret|non-secret)"
    r"(?::(?P<constraints>.*))?$"
)


def _parse_field(spec: str) -> FieldSpec:
    """Распарсить ``name:type:default:visibility[:constraints]``.

    Default может содержать двоеточия (URL, host:port) — regex берёт его
    как минимально-жадную середину между type и visibility.
    """
    m = _FIELD_RE.match(spec)
    if m is None:
        raise ValueError(
            f"--field={spec!r}: формат должен быть "
            "name:type:default:visibility[:constraints]"
        )
    name = m.group("name")
    type_ = m.group("type")
    default = m.group("default")
    visibility = m.group("visibility")
    constraints_str = m.group("constraints") or ""
    constraints = tuple(c for c in constraints_str.split(",") if c)

    # default может быть в кавычках — снимем их.
    if len(default) >= 2 and default[0] == default[-1] and default[0] in '"\'':
        default = default[1:-1]
    return FieldSpec(
        name=name, type_=type_, default=default, visibility=visibility,
        constraints=constraints,
    )


def _backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))


def _render_class_module(name: str, env_prefix: str, fields: list[FieldSpec]) -> str:
    """Сгенерировать содержимое ``services/<name>.py``."""
    cls_name = "".join(p.capitalize() for p in name.split("_")) + "Settings"
    singleton = f"{name}_settings"
    field_defs: list[str] = []
    for f in fields:
        kw_parts: list[str] = [f.python_default_literal]
        if f.constraints:
            kw_parts.extend(f.constraints)
        kw_parts.append(f'description="TODO: описание поля {f.name}"')
        body = ",\n        ".join(kw_parts)
        field_defs.append(f"    {f.name}: {f.type_} = Field(\n        {body},\n    )")
    fields_block = "\n".join(field_defs) if field_defs else "    pass"
    return (
        '"""Сгенерировано tools/codegen_settings.py — настройки '
        f'{cls_name}."""\n\n'
        "from typing import ClassVar\n\n"
        "from pydantic import Field\n"
        "from pydantic_settings import SettingsConfigDict\n\n"
        "from src.core.config.config_loader import BaseSettingsWithLoader\n\n\n"
        f"class {cls_name}(BaseSettingsWithLoader):\n"
        f'    """Настройки сервиса {name}."""\n\n'
        f'    yaml_group: ClassVar[str] = "{name}"\n'
        f'    model_config = SettingsConfigDict(\n'
        f'        env_prefix="{env_prefix}", extra="forbid"\n'
        f'    )\n\n'
        f"{fields_block}\n\n\n"
        f"{singleton} = {cls_name}()\n"
    )


def _render_yaml_section(name: str, fields: list[FieldSpec]) -> str:
    non_secret = [f for f in fields if not f.is_secret]
    if not non_secret:
        return f"\n# ────────── {name} (codegen) ──────────\n{name}:\n  {{}}\n"
    lines = [f"\n# ────────── {name} (codegen) ──────────", f"{name}:"]
    for f in non_secret:
        lines.append(f"  {f.name}: {f.yaml_default_literal}")
    return "\n".join(lines) + "\n"


def _render_env_section(env_prefix: str, fields: list[FieldSpec]) -> str:
    secrets = [f for f in fields if f.is_secret]
    if not secrets:
        return ""
    lines = [f"\n# ── {env_prefix.rstrip('_')} secrets (codegen) ──"]
    for f in secrets:
        lines.append(f"{env_prefix}{f.name.upper()}=")
    return "\n".join(lines) + "\n"


def _ensure_no_existing_class(name: str) -> None:
    target = SERVICES_DIR / f"{name}.py"
    if target.exists():
        raise FileExistsError(
            f"{target.relative_to(ROOT)} уже существует — codegen не "
            "перезаписывает существующие модули. Удалите файл вручную "
            "или используйте другое имя."
        )


def _patch_services_init(name: str) -> None:
    """Добавить re-export в services/__init__.py (idempotent).

    Регэксп ищет блок ``__all__ = ( ... )`` и расширяет его указанными
    именами. Импорт добавляется перед ``__all__``.
    """
    cls_name = "".join(p.capitalize() for p in name.split("_")) + "Settings"
    singleton = f"{name}_settings"
    text = SERVICES_INIT.read_text(encoding="utf-8")
    if cls_name in text:
        return
    _backup(SERVICES_INIT)
    new_import = (
        f"from src.core.config.services.{name} import {cls_name}, {singleton}\n"
    )
    marker = "__all__ = ("
    extra = f'    "{cls_name}",\n    "{singleton}",\n'
    if marker not in text:
        text = text.rstrip() + "\n" + new_import + f"\n{marker}\n{extra})\n"
    else:
        idx = text.find(marker)
        text = text[:idx] + new_import + text[idx:]
        m = re.search(r"__all__\s*=\s*\(", text)
        if m is None:  # pragma: no cover — marker уже проверен выше
            raise RuntimeError(f"{SERVICES_INIT.name}: блок __all__ повреждён")
        close = text.index(")", m.end())
        text = text[:close] + extra + text[close:]
    SERVICES_INIT.write_text(text, encoding="utf-8")


def _patch_settings_root(name: str) -> None:
    """Добавить import и атрибут в Settings (idempotent, AST-driven)."""
    cls_name = "".join(p.capitalize() for p in name.split("_")) + "Settings"
    singleton = f"{name}_settings"
    text = SETTINGS_FILE.read_text(encoding="utf-8")
    if f"{name}: {cls_name}" in text:
        return
    _backup(SETTINGS_FILE)

    # 1. Добавить импорт после блока services.
    services_import_marker = "from src.core.config.services import ("
    if services_import_marker in text:
        # Расширяем существующий блок — самый чистый путь.
        block_start = text.index(services_import_marker)
        block_end = text.index(")", block_start)
        block = text[block_start:block_end]
        inserted = (
            block.rstrip()
            + f"\n    {cls_name},\n    {singleton},\n"
        )
        text = text[:block_start] + inserted + text[block_end:]
    else:
        # Fallback: добавим отдельный импорт.
        text = (
            text.replace(
                "__all__ = (",
                f"from src.core.config.services.{name} import "
                f"{cls_name}, {singleton}\n\n__all__ = (",
                1,
            )
        )

    # 2. Добавить атрибут перед `class Settings(... )` блоком — в самом конце.
    attr_line = f"    {name}: {cls_name} = {singleton}\n"
    # Вставка перед строкой "@lru_cache".
    text = text.replace("\n\n@lru_cache()", f"\n{attr_line}\n\n@lru_cache()", 1)
    SETTINGS_FILE.write_text(text, encoding="utf-8")


def _append_yaml_section(name: str, fields: list[FieldSpec]) -> None:
    """Добавить секцию в base.yml (idempotent)."""
    text = BASE_YAML.read_text(encoding="utf-8")
    section_marker = f"\n{name}:"
    if section_marker in text or text.startswith(f"{name}:"):
        return
    _backup(BASE_YAML)
    BASE_YAML.write_text(
        text.rstrip() + "\n" + _render_yaml_section(name, fields), encoding="utf-8"
    )


def _append_env_section(env_prefix: str, fields: list[FieldSpec]) -> None:
    """Добавить ENV-записи в .env.example (idempotent)."""
    secrets = [f for f in fields if f.is_secret]
    if not secrets:
        return
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    block = _render_env_section(env_prefix, fields)
    expected_keys = [f"{env_prefix}{f.name.upper()}=" for f in secrets]
    if all(k in text for k in expected_keys):
        return
    _backup(ENV_EXAMPLE)
    ENV_EXAMPLE.write_text(text.rstrip() + "\n" + block, encoding="utf-8")


def _validate_python_syntax(*paths: Path) -> None:
    for p in paths:
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise RuntimeError(f"После codegen {p.name} имеет syntax error: {exc}") from exc


def _run_audit() -> int:
    """Прогнать config_audit.py, возвращает exit code (0=OK)."""
    if not CONFIG_AUDIT.exists():
        return 0
    res = subprocess.run(  # noqa: S603 — фиксированный sys.executable + локальный путь
        [sys.executable, str(CONFIG_AUDIT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(res.stdout)
    sys.stderr.write(res.stderr)
    return res.returncode


def cmd_new(args: argparse.Namespace) -> int:
    name: str = args.name
    env_prefix: str = args.env_prefix
    if not _NAME_RE.match(name):
        print(f"Неверное --name={name!r}: ожидается [a-z][a-z0-9_]*", file=sys.stderr)
        return 1
    if not _ENV_PREFIX_RE.match(env_prefix):
        print(
            f"Неверное --env-prefix={env_prefix!r}: ожидается [A-Z][A-Z0-9_]*_",
            file=sys.stderr,
        )
        return 1

    try:
        fields = [_parse_field(s) for s in (args.field or [])]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not fields:
        print("Нужно указать хотя бы один --field", file=sys.stderr)
        return 1

    try:
        _ensure_no_existing_class(name)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    target = SERVICES_DIR / f"{name}.py"
    target.write_text(_render_class_module(name, env_prefix, fields), encoding="utf-8")
    _patch_services_init(name)
    _patch_settings_root(name)
    _append_yaml_section(name, fields)
    _append_env_section(env_prefix, fields)

    _validate_python_syntax(target, SERVICES_INIT, SETTINGS_FILE)

    print(f"[codegen] создан {target.relative_to(ROOT)}")
    print(f"[codegen] секция {name}: добавлена в config_profiles/base.yml")
    print(f"[codegen] импорт {name}_settings зарегистрирован в settings.py")
    if any(f.is_secret for f in fields):
        print(f"[codegen] {sum(1 for f in fields if f.is_secret)} secret env-записи "
              "добавлены в .env.example")
    print()
    print("[codegen] запуск config_audit для самопроверки…")
    return _run_audit()


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="Создать новый Settings-класс")
    new.add_argument("--name", required=True, help="snake_case имя группы (kafka)")
    new.add_argument(
        "--env-prefix", required=True,
        help="UPPER_SNAKE_ ENV-префикс (KAFKA_)",
    )
    new.add_argument(
        "--field", action="append",
        help="name:type:default:visibility[:constraints] (повторяемый)",
    )
    new.set_defaults(func=cmd_new)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
