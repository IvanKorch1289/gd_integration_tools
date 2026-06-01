"""Двусторонний аудит конфигурации (W20.1+W20.2).

Сверяет YAML-конфигурацию (``config_profiles/base.yml`` + overlay активного
профиля) с моделями ``BaseSettingsWithLoader`` из ``src/core/config/``.

Прямой аудит (YAML → код):
    * orphan-ключи: top-level group без класса с таким ``yaml_group``;
    * orphan-ключи: вложенный ключ без поля в ``model_fields``.

Обратный аудит (код → конфиг):
    * missing-non-secret: required (no default), non-secret, non-computed
      поле, отсутствующее в merged YAML;
    * missing-secret: secret-поле (по имени или ``SecretStr``),
      отсутствующее в ``.env.example``.

Использование::

    python tools/config_audit.py [--profile dev|dev_light|staging|prod] [--strict]

При обнаружении любых проблем процесс завершается с кодом 1.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "src" / "core" / "config"
PROFILES_DIR = ROOT / "config_profiles"
ENV_EXAMPLE = ROOT / ".env.example"

PROFILES: tuple[str, ...] = ("dev", "dev_light", "staging", "prod")

SECRET_EXACT_NAMES: frozenset[str] = frozenset(
    {"password", "secret_key", "api_key", "access_key", "token", "username"}
)

# Поле считается секретом, если его имя оканчивается на один из этих
# суффиксов (с разделителем ``_``), но это не отменяет type-based
# exclusion (см. ``NON_SECRET_TYPE_HINTS``).
SECRET_SUFFIXES: tuple[str, ...] = (
    "password",
    "secret",
    "secret_key",
    "api_key",
    "access_key",
    "token",
)

# Если annotation содержит один из этих корней — поле точно НЕ секрет:
# списки/словари/счётчики/флаги/литералы не могут хранить чувствительные
# текстовые значения.
NON_SECRET_TYPE_HINTS: tuple[str, ...] = (
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "set",
    "Literal",
    "Path",
)


# ──────────────────── Models ────────────────────


@dataclass(slots=True)
class FieldSpec:
    """Описание поля настроек."""

    name: str
    annotation: str
    has_default: bool
    is_computed: bool

    @property
    def is_secret(self) -> bool:
        ann = self.annotation
        if "SecretStr" in ann:
            return True
        if any(re.search(rf"\b{t}\b", ann) for t in NON_SECRET_TYPE_HINTS):
            return False
        if self.name in SECRET_EXACT_NAMES:
            return True
        return any(
            self.name == s or self.name.endswith(f"_{s}") for s in SECRET_SUFFIXES
        )


@dataclass(slots=True)
class ClassSpec:
    """AST-описание класса настроек."""

    name: str
    bases: list[str]
    yaml_group: str | None = None
    env_prefix: str | None = None
    own_fields: dict[str, FieldSpec] = field(default_factory=dict)


# ──────────────────── AST parsing ────────────────────


def _ann_to_str(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover — устойчивость к незнакомым AST
        return ""


def _find_kw(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _has_default(value: ast.expr | None) -> bool:
    """Определяет, есть ли у поля default или default_factory.

    Соглашение pydantic: ``Field(default, ...)`` — первый positional
    аргумент трактуется как default value. ``Field(...)`` (Ellipsis)
    означает required-поле.
    """
    if value is None:
        return False
    if not isinstance(value, ast.Call):
        # ``foo: int = 5`` — есть default
        return True
    func = value.func
    func_name = (
        func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    )
    if func_name != "Field":
        # Иная фабрика — считаем, что default есть
        return True
    if value.args:
        first = value.args[0]
        if isinstance(first, ast.Constant) and first.value is Ellipsis:
            return False
        return True  # любой иной positional трактуется как default
    if _find_kw(value, "default") is not None:
        return True
    if _find_kw(value, "default_factory") is not None:
        return True
    return False


def _is_computed(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for dec in stmt.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = getattr(target, "id", None) or getattr(target, "attr", None)
        if name == "computed_field":
            return True
    return False


def _extract_class(node: ast.ClassDef) -> ClassSpec:
    spec = ClassSpec(name=node.name, bases=[_ann_to_str(b) for b in node.bases])
    computed_names: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_computed(
            stmt
        ):
            computed_names.add(stmt.name)
            continue
        # ``model_config = SettingsConfigDict(...)`` — обычное присваивание.
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == "model_config"
            and isinstance(stmt.value, ast.Call)
        ):
            prefix = _find_kw(stmt.value, "env_prefix")
            if isinstance(prefix, ast.Constant) and isinstance(prefix.value, str):
                spec.env_prefix = prefix.value
            continue
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target = stmt.target.id
            if target == "yaml_group":
                if isinstance(stmt.value, ast.Constant) and isinstance(
                    stmt.value.value, str
                ):
                    spec.yaml_group = stmt.value.value
                continue
            if target == "model_config":
                if isinstance(stmt.value, ast.Call):
                    prefix = _find_kw(stmt.value, "env_prefix")
                    if isinstance(prefix, ast.Constant) and isinstance(
                        prefix.value, str
                    ):
                        spec.env_prefix = prefix.value
                continue
            spec.own_fields[target] = FieldSpec(
                name=target,
                annotation=_ann_to_str(stmt.annotation),
                has_default=_has_default(stmt.value),
                is_computed=False,
            )
    # computed property через @property тоже исключаем
    for name in computed_names:
        spec.own_fields.pop(name, None)
    return spec


def _parse_config_classes(directory: Path) -> dict[str, ClassSpec]:
    registry: dict[str, ClassSpec] = {}
    for py in directory.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                spec = _extract_class(node)
                registry[spec.name] = spec
    return registry


def _resolve_fields(
    spec: ClassSpec, registry: dict[str, ClassSpec]
) -> dict[str, FieldSpec]:
    """Собирает все поля класса с учётом наследования (own override base)."""
    fields: dict[str, FieldSpec] = {}
    for base in spec.bases:
        base_spec = registry.get(base)
        if base_spec:
            fields.update(_resolve_fields(base_spec, registry))
    fields.update(spec.own_fields)
    return fields


def _resolve_yaml_group(spec: ClassSpec, registry: dict[str, ClassSpec]) -> str | None:
    if spec.yaml_group:
        return spec.yaml_group
    for base in spec.bases:
        base_spec = registry.get(base)
        if base_spec is None:
            continue
        if base_spec.yaml_group:
            return base_spec.yaml_group
        nested = _resolve_yaml_group(base_spec, registry)
        if nested:
            return nested
    return None


def _resolve_env_prefix(spec: ClassSpec, registry: dict[str, ClassSpec]) -> str:
    if spec.env_prefix is not None:
        return spec.env_prefix
    for base in spec.bases:
        base_spec = registry.get(base)
        if base_spec and base_spec.env_prefix is not None:
            return base_spec.env_prefix
    return ""


def _settings_classes(
    registry: dict[str, ClassSpec],
) -> dict[str, tuple[ClassSpec, dict[str, FieldSpec], str]]:
    """Возвращает ``{yaml_group: (spec, fields, env_prefix)}``.

    Включает только классы с разрешённым ``yaml_group`` (есть и не равен
    базовому-абстрактному None).
    """
    out: dict[str, tuple[ClassSpec, dict[str, FieldSpec], str]] = {}
    for spec in registry.values():
        group = _resolve_yaml_group(spec, registry)
        if not group or spec.yaml_group is None:
            # Берём только классы, у которых yaml_group объявлен непосредственно
            # (иначе попадут абстрактные базовые).
            continue
        fields = _resolve_fields(spec, registry)
        prefix = _resolve_env_prefix(spec, registry)
        out[group] = (spec, fields, prefix)
    return out


# ──────────────────── YAML / .env loaders ────────────────────


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: ожидался mapping на верхнем уровне")
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _load_profile_yaml(profile: str) -> dict[str, Any]:
    base = _read_yaml(PROFILES_DIR / "base.yml")
    overlay = _read_yaml(PROFILES_DIR / f"{profile}.yml")
    return _deep_merge(base, overlay)


def _load_env_keys() -> set[str]:
    if not ENV_EXAMPLE.is_file():
        return set()
    keys: set[str] = set()
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


# ──────────────────── Audit ────────────────────


@dataclass(slots=True)
class GroupReport:
    group: str
    class_name: str
    orphan_keys: list[str] = field(default_factory=list)
    missing_non_secret: list[str] = field(default_factory=list)
    missing_secret: list[str] = field(default_factory=list)

    def has_issues(self) -> bool:
        return bool(self.orphan_keys or self.missing_non_secret or self.missing_secret)


def _audit_group(
    group: str,
    class_name: str,
    fields: dict[str, FieldSpec],
    env_prefix: str,
    yaml_section: dict[str, Any] | None,
    env_keys: set[str],
) -> GroupReport:
    report = GroupReport(group=group, class_name=class_name)
    yaml_section = yaml_section or {}

    for key in yaml_section:
        if key not in fields:
            report.orphan_keys.append(key)

    for fname, fspec in fields.items():
        if fspec.is_computed:
            continue
        if fspec.is_secret:
            env_key = f"{env_prefix}{fname.upper()}"
            if env_key not in env_keys:
                report.missing_secret.append(env_key)
            continue
        if fspec.has_default:
            continue
        if fname not in yaml_section:
            report.missing_non_secret.append(fname)

    return report


def _audit_profile(
    profile: str,
    classes: dict[str, tuple[ClassSpec, dict[str, FieldSpec], str]],
    env_keys: set[str],
) -> tuple[list[GroupReport], list[str]]:
    yaml_data = _load_profile_yaml(profile)
    reports: list[GroupReport] = []
    orphan_groups: list[str] = []
    for top in yaml_data:
        if top not in classes:
            orphan_groups.append(top)
    for group, (spec, fields, prefix) in sorted(classes.items()):
        section = yaml_data.get(group)
        if section is None:
            section = {}
        if not isinstance(section, dict):
            section = {}
        reports.append(
            _audit_group(group, spec.name, fields, prefix, section, env_keys)
        )
    return reports, orphan_groups


# ──────────────────── Reporting ────────────────────


def _format_profile(
    profile: str, reports: list[GroupReport], orphan_groups: list[str]
) -> str:
    lines: list[str] = [f"## profile: {profile}"]
    issue_count = 0
    if orphan_groups:
        lines.append(f"  [ORPHAN-GROUP] {', '.join(orphan_groups)}")
        issue_count += len(orphan_groups)
    for r in reports:
        if not r.has_issues():
            continue
        lines.append(f"  [{r.group}] ({r.class_name})")
        for k in r.orphan_keys:
            lines.append(f"    [orphan]            {k}")
            issue_count += 1
        for k in r.missing_non_secret:
            lines.append(f"    [missing-non-secret] {k}")
            issue_count += 1
        for k in r.missing_secret:
            lines.append(f"    [missing-secret]    {k}")
            issue_count += 1
    if issue_count == 0:
        lines.append("  OK: 0 issues")
    else:
        lines.append(f"  TOTAL ISSUES: {issue_count}")
    return "\n".join(lines)


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        help="Проверить только указанный профиль (по умолчанию — все).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Совместимый алиас: всегда возвращает exit 1 при любых issues.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    registry = _parse_config_classes(CONFIG_DIR)
    classes = _settings_classes(registry)
    env_keys = _load_env_keys()

    profiles = (args.profile,) if args.profile else PROFILES

    print(
        f"Discovered {len(classes)} settings classes "
        f"in {CONFIG_DIR.relative_to(ROOT)}; "
        f"{len(env_keys)} keys in .env.example."
    )
    print()

    has_issues = False
    for profile in profiles:
        reports, orphan_groups = _audit_profile(profile, classes, env_keys)
        print(_format_profile(profile, reports, orphan_groups))
        print()
        if orphan_groups or any(r.has_issues() for r in reports):
            has_issues = True

    if has_issues:
        print("FAIL: конфигурация рассинхронизирована с моделями.")
        return 1
    print("OK: конфигурация полностью синхронизирована.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
