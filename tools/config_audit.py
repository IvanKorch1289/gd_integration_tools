"""Двусторонний аудит конфигурации (W20.1+W20.2) + CI-гейт (Wave 13 Q16).

Сверяет YAML-конфигурацию (``config_profiles/base.yml`` + overlay активного
профиля) с моделями ``BaseSettingsWithLoader`` из ``src/backend/core/config/``.

Прямой аудит (YAML → код):
    * orphan-ключи: top-level group без класса с таким ``yaml_group``;
    * orphan-ключи: вложенный ключ без поля в ``model_fields``.

Обратный аудит (код → конфиг):
    * missing-non-secret: required (no default), non-secret, non-computed
      поле, отсутствующее в merged YAML;
    * missing-secret: secret-поле (по имени или ``SecretStr``),
      отсутствующее в ``.env.example``.

Зачем гейт (Wave 13 Q16)
------------------------
Механизм загрузки конфигурации ТИХО отбрасывает неизвестные YAML-ключи
(``FilteredSettingsSource._filter_data``): опечатка в имени = тихая потеря
настройки. Этот инструмент находит такие расхождения, но раньше не был
подключён к CI и не покрыт тестами.

Два класса расхождений
----------------------
* **orphan-класс** (``orphan-group`` / ``orphan-key``) — наш дефект: ключ
  в YAML без поля в модели = опечатка = тихая потеря настройки. Это
  блокирующий scope гейта (по умолчанию ``--scope orphans``).
* **missing-класс** (``missing-secret`` / ``missing-non-secret``) — дефект
  другого рода: переменные окружения из Settings-классов не документированы
  в ``.env.example``. Секреты (``missing-secret``) блокируют гейт в scope
  ``--scope missing`` (ADR-0373: «в .env только секреты» — недокументированный
  секрет = риск bootstrap-fallback). ``missing-non-secret`` (поле не задано
  в YAML) остаётся неблокирующим и печатается отдельной секцией.

Известный долг зафиксирован в ``tools/config_audit_allowlist.txt`` (baseline
по всем видам расхождений); гейт падает только на **новых** расхождениях
в scope. ``--strict`` игнорирует baseline и падает на любых расхождениях
(scope=all).

Использование::

    python tools/config_audit.py [--profile dev|dev_light|staging|prod]
                                 [--scope orphans|missing|all] [--strict]
    python tools/config_audit.py --update-allowlist
    python tools/config_audit.py --json

Exit codes
----------
    0 — новых расхождений в scope нет (долг покрыт baseline).
    1 — появились новые расхождения в scope (или ``--strict`` при любых issues).
    2 — ошибка запуска (нет каталога моделей / каталога профилей).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
# cycle-7/D-AUDIT-701 fix: real path is src/backend/core/config/ (was src/core/config/)
CONFIG_DIR = ROOT / "src" / "backend" / "core" / "config"
PROFILES_DIR = ROOT / "config_profiles"
ENV_EXAMPLE = ROOT / ".env.example"

# Канонические правила распознавания секретов (ADR-0373) — общие для
# ``config_audit`` и ``check_env_example``. ``sys.path`` дополняется, чтобы
# скрипт работал и как ``python tools/config_audit.py``.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.config_secret_rules import (  # noqa: E402
    NON_SECRET_TYPE_HINTS,  # noqa: F401 — re-export для обратной совместимости
    is_secret_field,
)

#: Baseline известного долга (Wave 13 Q16).
ALLOWLIST_PATH = ROOT / "tools" / "config_audit_allowlist.txt"

PROFILES: tuple[str, ...] = ("dev", "dev_light", "staging", "prod")

#: Виды расхождений YAML ↔ модель настроек.
KIND_ORPHAN_GROUP = "orphan-group"
KIND_ORPHAN_KEY = "orphan-key"
KIND_MISSING_NON_SECRET = "missing-non-secret"  # noqa: S105 — не пароль, а вид issue
KIND_MISSING_SECRET = "missing-secret"  # noqa: S105 — не пароль, а вид issue

#: Orphan-класс — наш дефект (опечатка в YAML-ключе = тихая потеря настройки).
#: Блокирующий scope гейта по умолчанию.
_ORPHAN_KINDS: tuple[str, ...] = (KIND_ORPHAN_GROUP, KIND_ORPHAN_KEY)

#: Missing-класс — переменные окружения не документированы в ``.env.example``.
#: ``missing-secret`` блокирует гейт в scope ``missing`` (ADR-0373).
_MISSING_KINDS: tuple[str, ...] = (KIND_MISSING_NON_SECRET, KIND_MISSING_SECRET)

#: Блокирующие виды расхождений scope ``missing`` — секрет не документирован.
_MISSING_SECRET_KINDS: tuple[str, ...] = (KIND_MISSING_SECRET,)

_ALL_KINDS: tuple[str, ...] = _ORPHAN_KINDS + _MISSING_KINDS

#: Блокирующие scope гейта.
SCOPE_ORPHANS = "orphans"
SCOPE_MISSING = "missing"
SCOPE_ALL = "all"

_DEFAULT_REASON = "известный долг конфига (baseline Wave 13 Q16)"

#: Имена полей-секретов и эвристика их распознавания вынесены в
#: ``tools/config_secret_rules.py`` (ADR-0373) — общий источник правды для
#: этого гейта и ``tools/check_env_example.py``. Здесь остаётся re-export
#: для обратной совместимости импортов.
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

#: Типы, которые физически не могут хранить чувствительное значение
#: (списки/словари/счётчики/флаги/литералы/пути) — re-export из
#: ``tools/config_secret_rules.py`` (импорт выше).


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
        """Считается ли поле секретом (канонические правила ADR-0373)."""
        return is_secret_field(self.name, self.annotation)


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


def _load_profile_yaml(
    profile: str, profiles_dir: Path = PROFILES_DIR
) -> dict[str, Any]:
    """Читает и мержит ``base.yml`` + overlay профиля.

    Args:
        profile: Имя профиля (``dev``, ``dev_light``, ``staging``, ``prod``).
        profiles_dir: Каталог с YAML-профилями.

    Returns:
        Слитая конфигурация профиля.

    """
    base = _read_yaml(profiles_dir / "base.yml")
    overlay = _read_yaml(profiles_dir / f"{profile}.yml")
    return _deep_merge(base, overlay)


def _load_env_keys(path: Path = ENV_EXAMPLE) -> set[str]:
    """Собирает множество ключей из ``.env.example``.

    Args:
        path: Путь к файлу-шаблону окружения.

    Returns:
        Множество имён переменных окружения.

    """
    if not path.is_file():
        return set()
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
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
    """Отчёт аудита по одной YAML-секции.

    Attributes:
        group: Имя YAML-секции (``security``).
        class_name: Имя Settings-класса, которому соответствует секция.
        orphan_keys: YAML-ключи без поля в модели.
        missing_non_secret: Обязательные несекретные поля, которых нет в YAML.
        missing_secret: Секретные env-переменные, не документированные
            в ``.env.example``.

    """

    group: str
    class_name: str
    orphan_keys: list[str] = field(default_factory=list)
    missing_non_secret: list[str] = field(default_factory=list)
    missing_secret: list[str] = field(default_factory=list)

    def has_issues(self) -> bool:
        """Есть ли в секции хотя бы одно расхождение."""
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
    profiles_dir: Path = PROFILES_DIR,
) -> tuple[list[GroupReport], list[str]]:
    """Аудит одного профиля.

    Args:
        profile: Имя профиля.
        classes: Найденные Settings-классы (``yaml_group → (spec, fields, prefix)``).
        env_keys: Ключи из ``.env.example``.
        profiles_dir: Каталог с YAML-профилями.

    Returns:
        Кортеж ``(отчёты по секциям, orphan-группы)``.

    """
    yaml_data = _load_profile_yaml(profile, profiles_dir)
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


@dataclass(frozen=True, slots=True)
class Finding:
    """Одно расхождение между YAML-конфигом и моделями настроек.

    Attributes:
        kind: Вид расхождения (``orphan-group`` / ``orphan-key`` /
            ``missing-non-secret`` / ``missing-secret``).
        profile: Профиль, в котором обнаружено расхождение.
        group: Секция YAML (пусто для ``orphan-group``).
        name: Имя orphan-ключа / поля / переменной окружения.

    """

    kind: str
    profile: str
    group: str
    name: str

    @property
    def key(self) -> str:
        """Стабильный ключ расхождения (используется в allowlist)."""
        if self.kind == KIND_ORPHAN_GROUP:
            return f"{self.kind}:{self.profile}:{self.name}"
        return f"{self.kind}:{self.profile}:{self.group}:{self.name}"

    def as_dict(self) -> dict[str, str]:
        """Представляет расхождение для JSON-вывода."""
        return {
            "kind": self.kind,
            "profile": self.profile,
            "group": self.group,
            "name": self.name,
            "key": self.key,
        }


def _collect_findings(
    profile: str, reports: list[GroupReport], orphan_groups: list[str]
) -> list[Finding]:
    """Собирает плоский список расхождений по профилю.

    Args:
        profile: Имя профиля.
        reports: Отчёты по секциям YAML.
        orphan_groups: Секции YAML без соответствующего Settings-класса.

    Returns:
        Список расхождений, отсортированный по ключу.

    """
    findings: list[Finding] = [
        Finding(kind=KIND_ORPHAN_GROUP, profile=profile, group="", name=group)
        for group in orphan_groups
    ]
    for report in reports:
        findings.extend(
            Finding(kind=KIND_ORPHAN_KEY, profile=profile, group=report.group, name=key)
            for key in report.orphan_keys
        )
        findings.extend(
            Finding(
                kind=KIND_MISSING_NON_SECRET,
                profile=profile,
                group=report.group,
                name=name,
            )
            for name in report.missing_non_secret
        )
        findings.extend(
            Finding(
                kind=KIND_MISSING_SECRET, profile=profile, group=report.group, name=name
            )
            for name in report.missing_secret
        )
    return sorted(findings, key=lambda finding: finding.key)


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict[str, str]:
    """Читает allowlist (baseline известного долга).

    Args:
        path: Путь к allowlist-файлу.

    Returns:
        Словарь ``{ключ расхождения: inline-комментарий}``.

    """
    if not path.exists():
        return {}
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, comment = stripped.partition("#")
        entries[key.strip()] = comment.strip()
    return entries


def save_allowlist(path: Path, findings: list[Finding]) -> None:
    """Перегенерирует allowlist-файл текущим списком долга.

    Args:
        path: Путь к allowlist-файлу.
        findings: Расхождения, включаемые в baseline.

    """
    existing = load_allowlist(path)
    header = (
        "# Baseline рассинхронизации YAML-конфига и моделей настроек "
        "(Wave 13 Q16).\n"
        "# Формат: <kind>:<profile>:<group>:<name>  # owner=<team> | reason=<note>\n"
        "# Для orphan-группа формат короче: <kind>:<profile>:<section>\n"
        "# kind ∈ {orphan-group, orphan-key, missing-non-secret, missing-secret}.\n"
        "# Блокирующий scope гейта по умолчанию — orphan-класс\n"
        "# (orphan-group / orphan-key): опечатка в YAML-ключе = тихая потеря\n"
        "# настройки. Scope 'missing' блокирует missing-secret (секрет не\n"
        "# документирован в .env.example) — ADR-0373. missing-non-secret\n"
        "# (поле не задано в YAML) остаётся неблокирующим.\n"
        "# Каждая запись — известный долг; гейт падает только на НОВЫХ\n"
        "# расхождениях (не из этого списка).\n"
        "# Обновление: python tools/config_audit.py --update-allowlist\n"
        "\n"
    )
    lines: list[str] = []
    for finding in sorted(findings, key=lambda item: item.key):
        comment = existing.get(finding.key) or f"owner=core | reason={_DEFAULT_REASON}"
        lines.append(f"{finding.key}  # {comment}\n")
    path.write_text(header + "".join(lines), encoding="utf-8")


def _format_profile(
    profile: str,
    reports: list[GroupReport],
    orphan_groups: list[str],
    scope: str = SCOPE_ORPHANS,
) -> str:
    """Форматирует отчёт по профилю.

    Отчёт разделён на две секции: блокирующий orphan-класс и missing-класс
    (переменные окружения не документированы в ``.env.example`` / поля не
    заданы в YAML).

    Args:
        profile: Имя профиля.
        reports: Отчёты по секциям YAML.
        orphan_groups: Секции YAML без соответствующего Settings-класса.
        scope: Активный scope гейта (влияет на подпись missing-секции).

    Returns:
        Текстовый отчёт по профилю.

    """
    lines: list[str] = [f"## profile: {profile}"]

    orphan_count = 0
    if orphan_groups:
        lines.append(f"  [ORPHAN-GROUP] {', '.join(orphan_groups)}")
        orphan_count += len(orphan_groups)
    for report in reports:
        if not report.orphan_keys:
            continue
        lines.append(f"  [{report.group}] ({report.class_name})")
        for key in report.orphan_keys:
            lines.append(f"    [orphan]            {key}")
            orphan_count += 1
    if orphan_count:
        lines.append(f"  TOTAL ORPHAN ISSUES: {orphan_count}")
    else:
        lines.append("  OK: 0 orphan issues")

    missing_count = 0
    for report in reports:
        if not (report.missing_non_secret or report.missing_secret):
            continue
        lines.append(f"  [{report.group}] ({report.class_name})")
        for key in report.missing_non_secret:
            lines.append(f"    [missing-non-secret] {key}")
            missing_count += 1
        for key in report.missing_secret:
            lines.append(f"    [missing-secret]    {key}")
            missing_count += 1
    if missing_count:
        label = (
            "BLOCKING (missing-secret)"
            if scope == SCOPE_MISSING
            else "NON-BLOCKING (missing-*)"
        )
        lines.append(
            f"  {label}: {missing_count} "
            "(переменные не документированы в .env.example / поля не заданы в YAML)"
        )
    return "\n".join(lines)


def _build_argparser() -> argparse.ArgumentParser:
    """Собирает CLI-парсер гейта."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        help="Проверить только указанный профиль (по умолчанию — все).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Игнорировать baseline: всегда exit 1 при любых issues (scope=all).",
    )
    parser.add_argument(
        "--scope",
        choices=(SCOPE_ORPHANS, SCOPE_MISSING, SCOPE_ALL),
        default=SCOPE_ORPHANS,
        help=(
            "Что блокирует гейт: 'orphans' (только опечатки в YAML — "
            "наш дефект, по умолчанию), 'missing' (секреты не документированы "
            "в .env.example — ADR-0373) или 'all' (включая missing-*). "
        ),
    )
    parser.add_argument(
        "--config-dir",
        default=str(CONFIG_DIR),
        help="Каталог с моделями настроек (по умолчанию: src/backend/core/config).",
    )
    parser.add_argument(
        "--profiles-dir",
        default=str(PROFILES_DIR),
        help="Каталог с YAML-профилями (по умолчанию: config_profiles).",
    )
    parser.add_argument(
        "--env-example",
        default=str(ENV_EXAMPLE),
        help="Файл-шаблон окружения (по умолчанию: .env.example).",
    )
    parser.add_argument(
        "--allowlist",
        default=str(ALLOWLIST_PATH),
        help="Путь к allowlist-файлу (baseline известного долга).",
    )
    parser.add_argument(
        "--update-allowlist",
        action="store_true",
        help="Перегенерировать allowlist текущим списком долга.",
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON-вывод (для CI-интеграции)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа гейта.

    Args:
        argv: Аргументы CLI (по умолчанию — ``sys.argv[1:]``).

    Returns:
        0 — новых расхождений нет; 1 — новые расхождения (или ``--strict``
        при любых issues); 2 — ошибка запуска.

    """
    args = _build_argparser().parse_args(argv)

    config_dir = Path(args.config_dir)
    profiles_dir = Path(args.profiles_dir)
    env_example = Path(args.env_example)
    allowlist_path = Path(args.allowlist)

    missing = [
        path.as_posix() for path in (config_dir, profiles_dir) if not path.is_dir()
    ]
    if missing:
        print(
            "[config_audit] каталоги не найдены: " + ", ".join(missing), file=sys.stderr
        )
        return 2

    registry = _parse_config_classes(config_dir)
    classes = _settings_classes(registry)
    env_keys = _load_env_keys(env_example)

    # Аудит всегда идёт по всем профилям: baseline (allowlist) хранит ключи
    # с профилем, поэтому «stale» нельзя считать по одному профилю.
    reports_by_profile: dict[str, tuple[list[GroupReport], list[str]]] = {}
    findings_by_profile: dict[str, list[Finding]] = {}
    for profile in PROFILES:
        reports, orphan_groups = _audit_profile(
            profile, classes, env_keys, profiles_dir=profiles_dir
        )
        reports_by_profile[profile] = (reports, orphan_groups)
        findings_by_profile[profile] = _collect_findings(
            profile, reports, orphan_groups
        )

    all_findings = [f for profile in PROFILES for f in findings_by_profile[profile]]
    selected = (args.profile,) if args.profile else PROFILES
    selected_findings = [
        f for profile in selected for f in findings_by_profile[profile]
    ]

    # Блокирующий scope: orphan-класс (наш дефект) по умолчанию; scope
    # ``missing`` блокирует недокументированные секреты (ADR-0373).
    scope = SCOPE_ALL if args.strict else args.scope
    if scope == SCOPE_ALL:
        scope_kinds = _ALL_KINDS
    elif scope == SCOPE_MISSING:
        scope_kinds = _MISSING_SECRET_KINDS
    else:
        scope_kinds = _ORPHAN_KINDS
    blocking = [f for f in selected_findings if f.kind in scope_kinds]
    non_blocking = [f for f in selected_findings if f.kind not in scope_kinds]

    allowlist = load_allowlist(allowlist_path)
    scoped_allowlist = {
        key: comment
        for key, comment in allowlist.items()
        if key.split(":", 1)[0] in scope_kinds
    }
    if args.strict:
        # ``--strict`` игнорирует baseline: любое расхождение в scope → падение.
        new_findings = list(blocking)
        stale: list[str] = []
    else:
        new_findings = [f for f in blocking if f.key not in scoped_allowlist]
        current_keys = {
            finding.key
            for profile in PROFILES
            for finding in findings_by_profile[profile]
            if finding.kind in scope_kinds
        }
        stale = sorted(set(scoped_allowlist) - current_keys)

    if args.update_allowlist:
        save_allowlist(allowlist_path, all_findings)
        print(f"Allowlist обновлён: {len(all_findings)} запис(и/ей) → {allowlist_path}")
        return 0

    if args.json:
        payload = {
            "scope": scope,
            "total_findings": len(selected_findings),
            "blocking_findings": len(blocking),
            "new_violations": [finding.as_dict() for finding in new_findings],
            "non_blocking": [finding.as_dict() for finding in non_blocking],
            "allowlisted": sorted({f.key for f in blocking} & set(scoped_allowlist)),
            "stale_allowlist": stale,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if new_findings else 0

    print(
        f"Discovered {len(classes)} settings classes "
        f"in {_display_dir(config_dir)}; "
        f"{len(env_keys)} keys in {env_example.name}."
    )
    print()

    for profile in selected:
        reports, orphan_groups = reports_by_profile[profile]
        print(_format_profile(profile, reports, orphan_groups, scope=scope))
        print()

    if args.strict:
        if blocking:
            print(f"FAIL (strict): расхождений конфигурации — {len(blocking)}.")
            return 1
        print("OK: конфигурация полностью синхронизирована.")
        return 0

    if new_findings:
        print(f"НОВЫЕ расхождения конфигурации (scope={scope}): {len(new_findings)}")
        for finding in new_findings:
            print(f"  {finding.key}")
        print(
            "\nИсправьте YAML/модель либо внесите известный долг в baseline:\n"
            "  python tools/config_audit.py --update-allowlist"
        )
        return 1

    if stale:
        print(
            f"СТЕЙЛ записи в allowlist: {len(stale)} "
            "(расхождение исправлено — обновите allowlist)"
        )
        for key in stale[:10]:
            print(f"  {key}")
        if len(stale) > 10:
            print(f"  ... и ещё {len(stale) - 10}")

    print(
        f"Расхождений конфигурации: 0 новых "
        f"(scope={scope}; всего в долге: {len(selected_findings)}; "
        f"в scope: {len(blocking)}; неблокирующих: {len(non_blocking)}; "
        f"allowlist в scope: {len(scoped_allowlist)}; "
        f"allowlist всего: {len(allowlist)})"
    )
    return 0


def _display_dir(path: Path) -> str:
    """Возвращает путь относительно корня репозитория (для вывода)."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    sys.exit(main())
