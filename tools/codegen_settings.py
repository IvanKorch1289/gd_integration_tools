"""Settings codegen — атомарная генерация Settings-класса (W21.5a-e).

Команды
-------

* ``new`` (W21.5a) — императивный CLI: ``--name``, ``--env-prefix``,
  ``--field`` (повторяемый). Создаёт 5 артефактов за один проход.
* ``apply`` (W21.5b) — DSL-альтернатива: применить
  ``config-spec/<name>.yml`` идемпотентно.
* ``extract`` (W21.5d) — reverse-codegen: построить
  ``config-spec/<name>.yml`` из существующего ``<Name>Settings``.
* ``wizard`` (W21.5e) — интерактивный диалог через questionary.

Шаблоны (W21.5c)
----------------

Поле ``base`` в config-spec.yml выбирает родителя:

* ``BaseSettingsWithLoader`` (по умолчанию) — голый шаблон.
* ``BaseConnectorSettings`` — пул, retry, circuit breaker, health-check.
* ``BaseBotChannelSettings`` — bot-канал (api_base_url/signature/secrets).
* ``BaseQueueSettings`` — MQ-источник/синк (broker_url/batch/ack).

Контракт описания поля
----------------------

::

    name:type:default:visibility[:constraints]

* ``type ∈ {str, int, float, bool, str|None, int|None, float|None}``
* ``visibility ∈ {secret, non-secret}`` — secret уходит в
  ``.env.example``, non-secret — в ``base.yml``.
* ``constraints`` (optional, через запятую): ``ge=N``, ``le=N``,
  ``min_length=N``, ``max_length=N``, ``pattern=<regex>``.

Идемпотентность: повторный запуск не дублирует записи и не ломает
файлы. CST-правки выполняются через ``libcst`` с сохранением
форматирования и комментариев. ``.bak``-файлы не создаются — libcst
даёт round-trip-гарантии.

Завершается ``exit 1`` при любой ошибке валидации входа или конфликте
имён.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import libcst as cst
import libcst.matchers as m

ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = ROOT / "src" / "core" / "config" / "services"
SETTINGS_FILE = ROOT / "src" / "core" / "config" / "settings.py"
SERVICES_INIT = SERVICES_DIR / "__init__.py"
INTEGRATION_BASE = ROOT / "src" / "core" / "config" / "integration_base.py"
BASE_YAML = ROOT / "config_profiles" / "base.yml"
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG_SPEC_DIR = ROOT / "config-spec"
CONFIG_AUDIT = ROOT / "tools" / "config_audit.py"

_VALID_TYPES: frozenset[str] = frozenset(
    {"str", "int", "float", "bool", "str|None", "int|None", "float|None"}
)
_VALID_VISIBILITY: frozenset[str] = frozenset({"secret", "non-secret"})
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ENV_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*_$")
# Literal[...] — динамический тип; внутри допускаются строковые/числовые
# значения, но не вложенные ``]`` (для round-trip extract↔apply этого хватает).
_LITERAL_TYPE_RE = re.compile(r"^Literal\[[^\]]+\]$")


def _is_literal_type(type_: str) -> bool:
    """True, если ``type_`` — корректная аннотация ``Literal[...]``."""
    return bool(_LITERAL_TYPE_RE.match(type_))


def _is_valid_type(type_: str) -> bool:
    """Универсальная проверка типа поля: примитив или Literal[...]."""
    return type_ in _VALID_TYPES or _is_literal_type(type_)


# Реестр шаблонов: имя base-класса → модуль импорта.
TEMPLATES: dict[str, str] = {
    "BaseSettingsWithLoader": "src.backend.core.config.config_loader",
    "BaseConnectorSettings": "src.backend.core.config.integration_base",
    "BaseBotChannelSettings": "src.backend.core.config.integration_base",
    "BaseQueueSettings": "src.backend.core.config.integration_base",
    "BaseWebhookChannelSettings": "src.backend.core.config.integration_base",
    "BaseIntegrationSettings": "src.backend.core.config.integration_base",
}
DEFAULT_BASE = "BaseSettingsWithLoader"


# ────────────────────────── FieldSpec ──────────────────────────


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
        if _is_literal_type(self.type_):
            # Default уже хранится как сериализованный Python-литерал
            # (`"a"` / `1`). Если default пустой — берём первое значение.
            return self.default or _first_literal_value(self.type_)
        if "None" in self.type_ and self.default in ("", "None"):
            return "None"
        if self.type_ == "bool":
            return self.default if self.default in ("True", "False") else "False"
        if self.type_ in ("int", "int|None"):
            return self.default or "0"
        if self.type_ in ("float", "float|None"):
            return self.default or "0.0"
        return f'"{self.default}"'

    @property
    def yaml_default_literal(self) -> str:
        """Скаляр default'а для записи в base.yml (non-secret only).

        Для optional типов (``X|None``) пустой default = ``null``,
        иначе — по правилам конкретного типа.
        """
        if _is_literal_type(self.type_):
            value = self.default or _first_literal_value(self.type_)
            # YAML принимает Python-числа без кавычек, строки в кавычках
            # уже экранированы в исходном default.
            return value
        if "None" in self.type_ and self.default in ("", "None"):
            return "null"
        if self.type_ == "bool":
            return self.default.lower() if self.default else "false"
        if self.type_ in ("int", "int|None", "float", "float|None"):
            return self.default or "0"
        return self.default if self.default else '""'


def _first_literal_value(type_: str) -> str:
    """Вернуть первое допустимое значение из ``Literal[...]`` как Python-литерал."""
    inner = type_[len("Literal[") : -1]
    first = inner.split(",", 1)[0].strip()
    return first or '""'


_FIELD_RE = re.compile(
    r"^(?P<name>[a-z][a-z0-9_]*):"
    r"(?P<type>Literal\[[^\]]+\]|str\|None|int\|None|float\|None|str|int|float|bool):"
    r"(?P<default>.*?):"
    r"(?P<visibility>secret|non-secret)"
    r"(?::(?P<constraints>.*))?$"
)


def _parse_field(spec: str) -> FieldSpec:
    """Распарсить ``name:type:default:visibility[:constraints]``."""
    match = _FIELD_RE.match(spec)
    if match is None:
        raise ValueError(
            f"--field={spec!r}: формат должен быть "
            "name:type:default:visibility[:constraints]"
        )
    name = match.group("name")
    type_ = match.group("type")
    default = match.group("default")
    visibility = match.group("visibility")
    constraints_str = match.group("constraints") or ""
    constraints = tuple(c for c in constraints_str.split(",") if c)

    if len(default) >= 2 and default[0] == default[-1] and default[0] in "\"'":
        default = default[1:-1]
    return FieldSpec(
        name=name,
        type_=type_,
        default=default,
        visibility=visibility,
        constraints=constraints,
    )


# ────────────────────────── Class rendering ──────────────────────────


def _cls_name(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("_")) + "Settings"


def _singleton_name(name: str) -> str:
    return f"{name}_settings"


def _render_class_module(
    name: str, env_prefix: str, fields: list[FieldSpec], base: str = DEFAULT_BASE
) -> str:
    """Сгенерировать содержимое ``services/<name>.py``.

    base выбирается из ``TEMPLATES`` — см. описание модуля.
    """
    if base not in TEMPLATES:
        raise ValueError(
            f"base={base!r} не зарегистрирован. Доступные: {sorted(TEMPLATES)}"
        )
    cls = _cls_name(name)
    singleton = _singleton_name(name)
    has_literal = any(_is_literal_type(f.type_) for f in fields)
    field_defs: list[str] = []
    for f in fields:
        kw_parts: list[str] = [f.python_default_literal]
        if f.constraints:
            kw_parts.extend(f.constraints)
        kw_parts.append(f'description="TODO: описание поля {f.name}"')
        body = ",\n        ".join(kw_parts)
        field_defs.append(f"    {f.name}: {f.type_} = Field(\n        {body},\n    )")
    fields_block = "\n".join(field_defs) if field_defs else "    pass"
    base_module = TEMPLATES[base]
    typing_import = (
        "from typing import ClassVar, Literal\n"
        if has_literal
        else "from typing import ClassVar\n"
    )
    return (
        f'"""Сгенерировано tools/codegen_settings.py — настройки {cls}."""\n\n'
        f"{typing_import}\n"
        "from pydantic import Field\n"
        "from pydantic_settings import SettingsConfigDict\n\n"
        f"from {base_module} import {base}\n\n\n"
        f"class {cls}({base}):\n"
        f'    """Настройки сервиса {name}."""\n\n'
        f'    yaml_group: ClassVar[str] = "{name}"\n'
        "    model_config = SettingsConfigDict(\n"
        f'        env_prefix="{env_prefix}", extra="forbid"\n'
        "    )\n\n"
        f"{fields_block}\n\n\n"
        f"{singleton} = {cls}()\n"
    )


# ────────────────────────── libcst patches ──────────────────────────


def _matches_module(node: cst.ImportFrom, target_parts: tuple[str, ...]) -> bool:
    """Проверить, что ``node.module`` равен ``target_parts``."""
    if node.module is None:
        return False
    parts: list[str] = []
    cur: cst.BaseExpression | None = node.module
    while isinstance(cur, cst.Attribute):
        parts.append(cur.attr.value)
        cur = cur.value
    if isinstance(cur, cst.Name):
        parts.append(cur.value)
    parts.reverse()
    return tuple(parts) == target_parts


def _render_multiline_import(module_dotted: str, names: list[str]) -> str:
    """Сгенерировать многострочный ``from X import (\\n    A,\\n    B,\\n)``."""
    if len(names) == 1:
        return f"from {module_dotted} import {names[0]}\n"
    body = ",\n".join(f"    {n}" for n in names)
    return f"from {module_dotted} import (\n{body},\n)\n"


def _render_multiline_all(names: list[str]) -> str:
    """Сгенерировать многострочный ``__all__ = (\\n    "A",\\n    "B",\\n)``."""
    if len(names) == 1:
        return f'__all__ = ("{names[0]}",)\n'
    body = ",\n".join(f'    "{n}"' for n in names)
    return f"__all__ = (\n{body},\n)\n"


def _add_to_import_from(
    module: cst.Module, module_dotted: str, names: Iterable[str]
) -> tuple[cst.Module, bool]:
    """Расширить ``from <module_dotted> import (...)`` указанными именами.

    Идемпотентно. Если import существует — собирает объединённый набор
    имён (старые ∪ новые, отсортированно) и заменяет узел целиком на
    свежесгенерированный с правильным многострочным форматированием.
    Если import не найден — добавляет новый после последнего import-а.
    """
    target_parts = tuple(module_dotted.split("."))
    new_names = list(names)
    found_idx: int | None = None
    found_order: list[str] = []

    new_body = list(module.body)
    last_import_idx = -1
    for idx, stmt in enumerate(new_body):
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for sub in stmt.body:
            if isinstance(sub, (cst.Import, cst.ImportFrom)):
                last_import_idx = idx
            if isinstance(sub, cst.ImportFrom) and _matches_module(sub, target_parts):
                found_idx = idx
                if isinstance(sub.names, cst.ImportStar):
                    return module, False  # ничего не делаем
                for alias in sub.names:
                    raw = (
                        alias.asname.name.value
                        if alias.asname
                        else getattr(alias.name, "value", "")
                    )
                    if isinstance(raw, str) and raw:
                        found_order.append(raw)
                break

    found_set = set(found_order)
    to_add = [n for n in new_names if n not in found_set]
    if found_idx is not None and not to_add:
        return module, False

    # Порядок: исходный + новые в конце.
    merged = found_order + to_add if found_idx is not None else new_names
    rendered = cst.parse_statement(_render_multiline_import(module_dotted, merged))

    if found_idx is not None:
        new_body[found_idx] = rendered
    else:
        new_body.insert(last_import_idx + 1, rendered)
    return module.with_changes(body=tuple(new_body)), True


def _extend_all_tuple(
    module: cst.Module, names: Iterable[str]
) -> tuple[cst.Module, bool]:
    """Добавить элементы в кортеж ``__all__ = (...)``.

    Идемпотентно. Если ``__all__`` существует — собирает объединённый
    набор строк (старые ∪ новые, отсортированно) и заменяет узел
    целиком. Если ``__all__`` отсутствует — добавляет его в конец
    модуля.
    """
    new_names = list(names)
    new_body = list(module.body)
    found_idx: int | None = None
    found_order: list[str] = []

    for idx, stmt in enumerate(new_body):
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for sub in stmt.body:
            if not isinstance(sub, cst.Assign) or len(sub.targets) != 1:
                continue
            if not m.matches(sub.targets[0].target, m.Name("__all__")):
                continue
            value = sub.value
            if not isinstance(value, cst.Tuple):
                continue
            found_idx = idx
            for elem in value.elements:
                if isinstance(elem.value, cst.SimpleString):
                    raw = elem.value.value
                    found_order.append(raw.strip("'\""))
            break

    found_set = set(found_order)
    to_add = [n for n in new_names if n not in found_set]
    if found_idx is not None and not to_add:
        return module, False

    merged = found_order + to_add if found_idx is not None else new_names
    rendered = cst.parse_statement(_render_multiline_all(merged))

    if found_idx is not None:
        new_body[found_idx] = rendered
    else:
        new_body.append(rendered)
    return module.with_changes(body=tuple(new_body)), True


def _add_class_attribute(
    module: cst.Module, class_name: str, attr_name: str, attr_type: str, attr_value: str
) -> tuple[cst.Module, bool]:
    """Добавить ``<attr_name>: <attr_type> = <attr_value>`` в указанный класс.

    Идемпотентно: если атрибут уже есть — модуль возвращается без
    изменений. Атрибут добавляется в самый конец тела класса.
    """
    changed = False

    class _Transformer(cst.CSTTransformer):
        def leave_ClassDef(
            self, original_node: cst.ClassDef, updated_node: cst.ClassDef
        ) -> cst.ClassDef:
            nonlocal changed
            if updated_node.name.value != class_name:
                return updated_node
            for stmt in updated_node.body.body:
                if isinstance(stmt, cst.SimpleStatementLine):
                    for sub in stmt.body:
                        if isinstance(sub, cst.AnnAssign) and m.matches(
                            sub.target, m.Name(attr_name)
                        ):
                            return updated_node
            new_stmt = cst.parse_statement(
                f"{attr_name}: {attr_type} = {attr_value}\n",
                config=module.config_for_parsing,
            )
            new_body = list(updated_node.body.body)
            new_body.append(new_stmt)
            changed = True
            return updated_node.with_changes(
                body=updated_node.body.with_changes(body=tuple(new_body))
            )

    new_module = module.visit(_Transformer())
    return new_module, changed


def _patch_services_init(name: str) -> None:
    """Добавить re-export в ``services/__init__.py`` (idempotent)."""
    cls = _cls_name(name)
    singleton = _singleton_name(name)
    text = SERVICES_INIT.read_text(encoding="utf-8")
    module = cst.parse_module(text)
    module, _ = _add_to_import_from(
        module, f"src.backend.core.config.services.{name}", [cls, singleton]
    )
    module, _ = _extend_all_tuple(module, [cls, singleton])
    SERVICES_INIT.write_text(module.code, encoding="utf-8")


def _patch_settings_root(name: str) -> None:
    """Добавить import + атрибут ``Settings`` (idempotent, libcst)."""
    cls = _cls_name(name)
    singleton = _singleton_name(name)
    text = SETTINGS_FILE.read_text(encoding="utf-8")
    module = cst.parse_module(text)
    module, _ = _add_to_import_from(
        module, "src.backend.core.config.services", [cls, singleton]
    )
    module, _ = _add_class_attribute(module, "Settings", name, cls, singleton)
    SETTINGS_FILE.write_text(module.code, encoding="utf-8")


# ────────────────────────── YAML / .env writers ──────────────────────────


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


def _append_yaml_section(name: str, fields: list[FieldSpec]) -> None:
    text = BASE_YAML.read_text(encoding="utf-8")
    if f"\n{name}:" in text or text.startswith(f"{name}:"):
        return
    BASE_YAML.write_text(
        text.rstrip() + "\n" + _render_yaml_section(name, fields), encoding="utf-8"
    )


def _append_env_section(env_prefix: str, fields: list[FieldSpec]) -> None:
    secrets = [f for f in fields if f.is_secret]
    if not secrets:
        return
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    expected = [f"{env_prefix}{f.name.upper()}=" for f in secrets]
    if all(k in text for k in expected):
        return
    ENV_EXAMPLE.write_text(
        text.rstrip() + "\n" + _render_env_section(env_prefix, fields), encoding="utf-8"
    )


# ────────────────────────── Validation helpers ──────────────────────────


def _ensure_no_existing_class(name: str) -> None:
    target = SERVICES_DIR / f"{name}.py"
    if target.exists():
        raise FileExistsError(
            f"{target.relative_to(ROOT)} уже существует — codegen не "
            "перезаписывает существующие модули. Удалите файл вручную "
            "или используйте другое имя."
        )


def _validate_python_syntax(*paths: Path) -> None:
    for p in paths:
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise RuntimeError(
                f"После codegen {p.name} имеет syntax error: {exc}"
            ) from exc


def _run_audit() -> int:
    """Прогнать config_audit.py, возвращает exit code (0=OK)."""
    if not CONFIG_AUDIT.exists():
        return 0
    res = subprocess.run(  # noqa: S603 — фиксированный sys.executable
        [sys.executable, str(CONFIG_AUDIT)], cwd=ROOT, capture_output=True, text=True
    )
    sys.stdout.write(res.stdout)
    sys.stderr.write(res.stderr)
    return res.returncode


def _run_ruff(*paths: Path) -> None:
    """Применить ``ruff format`` и ``ruff check --fix`` к указанным файлам.

    libcst сохраняет строгое форматирование исходника, но добавление
    нового import-блока может нарушить isort-сортировку и пустые
    строки между секциями. ruff в режиме --fix приводит файлы к
    канону (PEP 8 + isort).

    Если ruff недоступен — тихо пропускаем (codegen-выход остаётся
    рабочим, просто не отполированным).
    """
    targets = [str(p) for p in paths if p.exists()]
    if not targets:
        return
    for argv in (
        ["ruff", "format", *targets],
        ["ruff", "check", "--fix", "--select", "I", *targets],
    ):
        try:
            subprocess.run(  # noqa: S603 — фиксированный argv
                argv, cwd=ROOT, capture_output=True, text=True, check=False
            )
        except FileNotFoundError:
            return


# ────────────────────────── Common applier ──────────────────────────


@dataclass(slots=True)
class CodegenSpec:
    """Полная спецификация одного Settings-класса (DSL-форма)."""

    name: str
    env_prefix: str
    base: str = DEFAULT_BASE
    fields: list[FieldSpec] = dc_field(default_factory=list)


def _validate_spec(spec: CodegenSpec) -> None:
    if not _NAME_RE.match(spec.name):
        raise ValueError(f"name={spec.name!r}: ожидается [a-z][a-z0-9_]*")
    if not _ENV_PREFIX_RE.match(spec.env_prefix):
        raise ValueError(f"env_prefix={spec.env_prefix!r}: ожидается [A-Z][A-Z0-9_]*_")
    if spec.base not in TEMPLATES:
        raise ValueError(
            f"base={spec.base!r} не зарегистрирован. Доступные: {sorted(TEMPLATES)}"
        )
    if not spec.fields:
        raise ValueError("fields пустой — должно быть хотя бы одно поле")
    for f in spec.fields:
        if not _is_valid_type(f.type_):
            raise ValueError(
                f"field={f.name!r}: тип {f.type_!r} не поддержан. "
                f"Допустимы: {sorted(_VALID_TYPES)} или Literal[...]"
            )


def _apply_spec(spec: CodegenSpec, *, run_audit: bool = True) -> int:
    """Применить ``CodegenSpec`` идемпотентно.

    Если класс уже существует — пропускает создание модуля и патчит
    только реэкспорт/Settings/yaml/env (заполняет недостающее).
    """
    target = SERVICES_DIR / f"{spec.name}.py"
    created = not target.exists()
    if created:
        target.write_text(
            _render_class_module(
                spec.name, spec.env_prefix, spec.fields, base=spec.base
            ),
            encoding="utf-8",
        )
    _patch_services_init(spec.name)
    _patch_settings_root(spec.name)
    _append_yaml_section(spec.name, spec.fields)
    _append_env_section(spec.env_prefix, spec.fields)
    _validate_python_syntax(target, SERVICES_INIT, SETTINGS_FILE)
    _run_ruff(target, SERVICES_INIT, SETTINGS_FILE)

    print(
        f"[codegen] {'создан' if created else 'актуализирован'} "
        f"{target.relative_to(ROOT)}"
    )
    print(f"[codegen] секция {spec.name}: добавлена в config_profiles/base.yml")
    print(
        f"[codegen] импорт {_singleton_name(spec.name)} зарегистрирован в settings.py"
    )
    if any(f.is_secret for f in spec.fields):
        print(
            f"[codegen] {sum(1 for f in spec.fields if f.is_secret)} secret "
            "env-записи добавлены в .env.example"
        )
    if not run_audit:
        return 0
    print()
    print("[codegen] запуск config_audit для самопроверки…")
    return _run_audit()


# ────────────────────────── Spec I/O (ruamel) ──────────────────────────


def _yaml_round_trip():
    """Создать ruamel YAML с round-trip настройками (комментарии, порядок)."""
    from ruamel.yaml import YAML

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _spec_from_yaml(path: Path) -> CodegenSpec:
    yaml = _yaml_round_trip()
    with open(path, encoding="utf-8") as fh:
        data = yaml.load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: ожидается mapping в корне")
    name = str(data.get("name", "")).strip()
    env_prefix = str(data.get("env_prefix", "")).strip()
    base = str(data.get("base", DEFAULT_BASE)).strip() or DEFAULT_BASE
    raw_fields = data.get("fields", []) or []
    if not isinstance(raw_fields, list):
        raise ValueError(f"{path}: 'fields' должно быть списком")
    fields: list[FieldSpec] = []
    for item in raw_fields:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: элемент fields должен быть mapping'ом")
        constraints_raw = item.get("constraints", []) or []
        if isinstance(constraints_raw, str):
            constraints = tuple(
                c.strip() for c in constraints_raw.split(",") if c.strip()
            )
        else:
            constraints = tuple(str(c) for c in constraints_raw)
        default_raw = item.get("default", "")
        default = "" if default_raw is None else str(default_raw)
        fields.append(
            FieldSpec(
                name=str(item["name"]),
                type_=str(item["type"]),
                default=default,
                visibility=str(item["visibility"]),
                constraints=constraints,
            )
        )
    spec = CodegenSpec(name=name, env_prefix=env_prefix, base=base, fields=fields)
    _validate_spec(spec)
    return spec


def _spec_to_yaml(spec: CodegenSpec, path: Path) -> None:
    """Сериализовать spec в config-spec/<name>.yml (round-trip)."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    yaml = _yaml_round_trip()
    root = CommentedMap()
    root["name"] = spec.name
    root["env_prefix"] = spec.env_prefix
    root["base"] = spec.base
    fields_seq = CommentedSeq()
    for f in spec.fields:
        item = CommentedMap()
        item["name"] = f.name
        item["type"] = f.type_
        item["default"] = f.default if f.default else ""
        item["visibility"] = f.visibility
        if f.constraints:
            item["constraints"] = list(f.constraints)
        fields_seq.append(item)
    root["fields"] = fields_seq
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(root, fh)


# ────────────────────────── Reverse codegen (extract) ──────────────────────────


_AST_LITERAL_NODES = (ast.Constant,)


def _stringify_ast_value(node: ast.AST) -> str:
    """Превратить ast-узел default'а в строковый литерал spec'а."""
    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"
        if isinstance(node.value, bool):
            return "True" if node.value else "False"
        return str(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return f"-{_stringify_ast_value(node.operand)}"
    return ast.unparse(node)


def _stringify_annotation(node: ast.AST) -> str:
    """Превратить ast-узел аннотации в строку ``_VALID_TYPES`` или ``Literal[...]``.

    Сохраняет ``Literal[...]`` как-есть (без пробелов), для всех остальных
    случаев приводит ``Optional[X]`` → ``X|None``.
    """
    raw = ast.unparse(node)
    text = raw.replace(" ", "")
    if text.startswith("Literal["):
        return text
    text = text.replace("Optional[", "")
    if text.endswith("]") and "Optional" in raw:
        text = text.rstrip("]")
        text = f"{text}|None"
    return text


def _extract_constraints(call: ast.Call) -> tuple[str, ...]:
    """Извлечь support-constraints из ``Field(..., ge=..., le=...)``."""
    keys = ("ge", "le", "min_length", "max_length", "pattern")
    parts: list[str] = []
    for kw in call.keywords:
        if kw.arg in keys:
            parts.append(f"{kw.arg}={_stringify_ast_value(kw.value)}")
    return tuple(parts)


def _classify_visibility(call: ast.Call) -> str:
    """Поле является ``secret``, если default = ``...`` (Ellipsis)."""
    for arg in call.args:
        if isinstance(arg, ast.Constant) and arg.value is Ellipsis:
            return "secret"
    for kw in call.keywords:
        if kw.arg == "default" and isinstance(kw.value, ast.Constant):
            if kw.value.value is Ellipsis:
                return "secret"
    return "non-secret"


def _extract_default(call: ast.Call) -> str:
    """Достать строковый default из ``Field(default, ...)`` или ``Field(default=...)``."""
    for arg in call.args:
        if isinstance(arg, ast.Constant) and arg.value is Ellipsis:
            return ""
        if isinstance(arg, _AST_LITERAL_NODES):
            return _stringify_ast_value(arg)
        if isinstance(arg, ast.UnaryOp):
            return _stringify_ast_value(arg)
    for kw in call.keywords:
        if kw.arg == "default":
            return _stringify_ast_value(kw.value)
    return ""


def extract_spec_from_class(cls_name: str) -> CodegenSpec:
    """Построить ``CodegenSpec`` по имени существующего Settings-класса.

    Поиск идёт по ``src/core/config/services/*.py``. Возвращает spec с
    исходными полями, готовый для ``_spec_to_yaml``.
    """
    candidates = list(SERVICES_DIR.glob("*.py"))
    for path in candidates:
        try:
            module_ast = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in module_ast.body:
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                return _build_spec_from_class_ast(node, path)
    try:
        shown = SERVICES_DIR.relative_to(ROOT)
    except ValueError:
        shown = SERVICES_DIR
    raise LookupError(f"Класс {cls_name} не найден в {shown}")


def _build_spec_from_class_ast(cls_node: ast.ClassDef, path: Path) -> CodegenSpec:
    name: str | None = None
    env_prefix: str | None = None
    base = DEFAULT_BASE
    if cls_node.bases:
        base_node = cls_node.bases[0]
        if isinstance(base_node, ast.Name):
            base = base_node.id
    fields: list[FieldSpec] = []
    for stmt in cls_node.body:
        # Простое присваивание: model_config = SettingsConfigDict(...)
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            tgt = stmt.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id == "model_config":
                env_prefix = _extract_env_prefix(stmt.value) or env_prefix
                continue
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target = stmt.target.id
            if target == "yaml_group":
                if isinstance(stmt.value, ast.Constant):
                    name = str(stmt.value.value)
                continue
            if target == "model_config":
                env_prefix = _extract_env_prefix(stmt.value) or env_prefix
                continue
            if (
                isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == "Field"
            ):
                fields.append(
                    FieldSpec(
                        name=target,
                        type_=_stringify_annotation(stmt.annotation),
                        default=_extract_default(stmt.value),
                        visibility=_classify_visibility(stmt.value),
                        constraints=_extract_constraints(stmt.value),
                    )
                )
    if not name:
        raise ValueError(
            f"{path}: класс {cls_node.name} без yaml_group — extract невозможен"
        )
    if not env_prefix:
        raise ValueError(f"{path}: класс {cls_node.name} без env_prefix в model_config")
    if base not in TEMPLATES:
        # Для обратной совместимости: если родитель не в реестре, берём дефолт
        # — extract предназначен для round-trip существующих классов.
        base = DEFAULT_BASE
    return CodegenSpec(name=name, env_prefix=env_prefix, base=base, fields=fields)


def _extract_env_prefix(value: ast.AST | None) -> str | None:
    if not isinstance(value, ast.Call):
        return None
    for kw in value.keywords:
        if kw.arg == "env_prefix" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None


# ────────────────────────── Wizard (questionary) ──────────────────────────


def _wizard_collect() -> CodegenSpec:
    import questionary

    name: str = questionary.text(
        "Имя группы (snake_case, например: kafka)",
        validate=lambda v: bool(_NAME_RE.match(v)) or "ожидается [a-z][a-z0-9_]*",
    ).ask()
    if name is None:
        raise KeyboardInterrupt
    suggested_prefix = name.upper() + "_"
    env_prefix: str = questionary.text(
        "ENV-префикс (UPPER_SNAKE_)",
        default=suggested_prefix,
        validate=lambda v: (
            bool(_ENV_PREFIX_RE.match(v)) or "ожидается [A-Z][A-Z0-9_]*_"
        ),
    ).ask()
    if env_prefix is None:
        raise KeyboardInterrupt
    base: str = questionary.select(
        "Базовый класс шаблона", choices=list(TEMPLATES.keys()), default=DEFAULT_BASE
    ).ask()
    if base is None:
        raise KeyboardInterrupt
    fields: list[FieldSpec] = []
    while True:
        more = questionary.confirm(
            f"Добавить поле? (всего: {len(fields)})", default=True
        ).ask()
        if more is None:
            raise KeyboardInterrupt
        if not more:
            if not fields:
                print("Нужно хотя бы одно поле.")
                continue
            break
        fields.append(_wizard_field())
    return CodegenSpec(name=name, env_prefix=env_prefix, base=base, fields=fields)


def _wizard_field() -> FieldSpec:
    import questionary

    fname: str = questionary.text(
        "  поле: имя",
        validate=lambda v: (
            bool(re.match(r"^[a-z][a-z0-9_]*$", v)) or "ожидается [a-z][a-z0-9_]*"
        ),
    ).ask()
    if fname is None:
        raise KeyboardInterrupt
    ftype: str = questionary.select(
        "  поле: тип", choices=sorted(_VALID_TYPES), default="str"
    ).ask()
    if ftype is None:
        raise KeyboardInterrupt
    visibility: str = questionary.select(
        "  поле: visibility", choices=sorted(_VALID_VISIBILITY), default="non-secret"
    ).ask()
    if visibility is None:
        raise KeyboardInterrupt
    if visibility == "secret":
        default = ""
    else:
        default = questionary.text(
            "  поле: default (пусто = '' для str / 0 для int / None для Optional)",
            default="",
        ).ask()
        if default is None:
            raise KeyboardInterrupt
    constraints_raw: str = questionary.text(
        "  поле: constraints (опц., через запятую: ge=1,le=10)", default=""
    ).ask()
    if constraints_raw is None:
        raise KeyboardInterrupt
    constraints = tuple(c.strip() for c in constraints_raw.split(",") if c.strip())
    return FieldSpec(
        name=fname,
        type_=ftype,
        default=default,
        visibility=visibility,
        constraints=constraints,
    )


# ────────────────────────── Commands ──────────────────────────


def cmd_new(args: argparse.Namespace) -> int:
    try:
        fields = [_parse_field(s) for s in (args.field or [])]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    spec = CodegenSpec(
        name=args.name, env_prefix=args.env_prefix, base=args.base, fields=fields
    )
    try:
        _validate_spec(spec)
        _ensure_no_existing_class(spec.name)
    except (ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return _apply_spec(spec)


def cmd_apply(args: argparse.Namespace) -> int:
    path = Path(args.spec)
    if not path.is_absolute():
        path = (CONFIG_SPEC_DIR / path).resolve() if path.parent == Path() else path
    if not path.exists():
        print(f"spec-файл не найден: {path}", file=sys.stderr)
        return 1
    try:
        spec = _spec_from_yaml(path)
    except (ValueError, KeyError) as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1
    return _apply_spec(spec)


def cmd_extract(args: argparse.Namespace) -> int:
    try:
        spec = extract_spec_from_class(args.cls)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else CONFIG_SPEC_DIR / f"{spec.name}.yml"
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()
    _spec_to_yaml(spec, out_path)
    try:
        shown = out_path.relative_to(ROOT)
    except ValueError:
        shown = out_path
    print(f"[extract] {args.cls} → {shown}")
    return 0


def cmd_wizard(args: argparse.Namespace) -> int:
    try:
        spec = _wizard_collect()
    except KeyboardInterrupt:
        print("\n[wizard] прерван пользователем", file=sys.stderr)
        return 130
    out_path = CONFIG_SPEC_DIR / f"{spec.name}.yml"
    _spec_to_yaml(spec, out_path)
    print(f"[wizard] spec сохранён: {out_path.relative_to(ROOT)}")
    if not args.no_apply:
        try:
            _ensure_no_existing_class(spec.name)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            print(
                "spec сохранён, но apply пропущен. "
                "Удалите существующий модуль и запустите apply вручную.",
                file=sys.stderr,
            )
            return 1
        return _apply_spec(spec)
    return 0


# ────────────────────────── CLI ──────────────────────────


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    new = sub.add_parser("new", help="Создать новый Settings-класс (CLI)")
    new.add_argument("--name", required=True, help="snake_case имя группы")
    new.add_argument("--env-prefix", required=True, help="UPPER_SNAKE_ ENV-префикс")
    new.add_argument(
        "--base",
        default=DEFAULT_BASE,
        choices=sorted(TEMPLATES),
        help="Базовый класс-шаблон",
    )
    new.add_argument(
        "--field",
        action="append",
        help="name:type:default:visibility[:constraints] (повторяемый)",
    )
    new.set_defaults(func=cmd_new)

    apply_p = sub.add_parser(
        "apply", help="Применить config-spec/<name>.yml (idempotent)"
    )
    apply_p.add_argument(
        "spec", help="Путь к YAML-спецификации (относительный = config-spec/<spec>)"
    )
    apply_p.set_defaults(func=cmd_apply)

    extract_p = sub.add_parser(
        "extract", help="Reverse: класс → config-spec/<name>.yml"
    )
    extract_p.add_argument("--cls", required=True, help="Имя Settings-класса")
    extract_p.add_argument(
        "--out",
        default=None,
        help="Куда сохранить (по умолчанию config-spec/<name>.yml)",
    )
    extract_p.set_defaults(func=cmd_extract)

    wiz = sub.add_parser("wizard", help="Интерактивный wizard через questionary")
    wiz.add_argument(
        "--no-apply", action="store_true", help="Только сохранить spec, без apply"
    )
    wiz.set_defaults(func=cmd_wizard)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
