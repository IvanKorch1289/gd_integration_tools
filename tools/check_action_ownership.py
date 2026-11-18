#!/usr/bin/env python3
"""Гейт владения action-обработчиками: «у action'а один владелец».

Класс дефекта
-------------
Action-обработчик может быть зарегистрирован в нескольких местах:
в ядре (``src/backend/dsl/commands/setup/``), в хуке плагина
(``extensions/*/plugin.py::on_register_actions``) и/или объявлен в
манифесте (``extensions/*/plugin.toml::provides.actions``). Такое
дублирование не безобидно:

* ``ActionRegistryAdapter`` (ядро) оборачивает handler плагина в
  ``ActionHandlerSpec`` **без** ``payload_model`` и перезаписывает spec
  из ядра — валидация request-body молча отключается (F-01e, волна 35);
* объявленный в двух манифестах action означает двух претендентов на
  владение и разные capability-декларации на один и тот же action.

Гейт не заменяет ``tools/check_layers.py`` (тот про статические импорты) —
он про **владение и семантику** регистрации.

Правило
-------
1. **Один владелец.** Action, зарегистрированный в двух и более местах
   (ядро + ядро, ядро + плагин, плагин + плагин), — нарушение.
2. **Согласованный ``payload_model``.** У разных владельцев одного
   action'а модели валидации payload должны совпадать (в том числе
   «оба не заданы»).
3. **Согласованные capability.** Набор capability, заявленный владельцем
   для action'а, должен совпадать у всех владельцев.
4. **Один манифест.** Action, объявленный в ``provides.actions`` двух
   манифестов, — нарушение (два претендента на публичный action).

Мягкие находки (не блокируют, блокируют в ``--strict``):
* action зарегистрирован плагином, но не объявлен в его манифесте;
* action объявлен в манифесте, но нигде не зарегистрирован.

Источники (по умолчанию)
------------------------
* ядро — ``src/backend/dsl/commands/setup/`` (каноническая регистрация
  доменных actions, ADR-0457);
* плагины — ``extensions/**/plugin.py`` (хук ``on_register_actions``);
* манифесты — ``extensions/**/plugin.toml`` (``provides.actions``).

Известные ограничения (ponytail: не раздуваем гейт)
----------------------------------------------------
* Регистрации, собираемые динамически (``@service_dsl``,
  ``ActionRouterBuilder``, ``notify_actions``), статически не разрешаются —
  гейт их не видит.
* Capability ядра на уровне action'а не декларируются ( capability-контур
  живёт в отдельных гейтах) — для ядра набор пуст; расхождение с
  capability плагина фиксируется как ``capability_mismatch``.

Запуск
------
::

    python tools/check_action_ownership.py            # проверка (exit 1 при нарушениях)
    python tools/check_action_ownership.py --json     # JSON-вывод
    python tools/check_action_ownership.py --strict   # мягкие находки тоже блокируют

Exit codes
----------
    0 — нарушений нет.
    1 — найдены нарушения владения.
    2 — ошибка сканирования (fail-closed: результат неполон → падать).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = (
    "ActionClaim",
    "Finding",
    "PluginManifest",
    "check_ownership",
    "main",
    "scan_claims",
    "scan_manifests",
)

_ROOT = Path(__file__).resolve().parents[1]

#: Каноническая точка регистрации actions в ядре (ADR-0457).
DEFAULT_CORE_ROOT = _ROOT / "src" / "backend" / "dsl" / "commands" / "setup"

#: Корень расширений: плагины (``plugin.py``) и манифесты (``plugin.toml``).
DEFAULT_EXTENSIONS_ROOT = _ROOT / "extensions"

#: Источник истины для CRUD-методов (``_register_crud_actions``).
_CRUD_METHODS_SOURCE = _ROOT / "src" / "backend" / "dsl" / "service_dsl.py"

#: Fallback, если исходник с ``_CRUD_METHODS`` не удалось разобрать.
_FALLBACK_CRUD_METHODS: tuple[str, ...] = ("add", "get", "update", "delete", "list")

#: Имя глобального реестра action-обработчиков ядра.
_CORE_OWNER = "core"

#: Имя хука плагина, в котором регистрируются actions.
_PLUGIN_HOOK = "on_register_actions"


@dataclass(frozen=True, slots=True)
class ActionClaim:
    """Одно место регистрации action-обработчика.

    Attributes:
        action: Имя action'а.
        owner: Владелец регистрации (``"core"`` или имя плагина).
        kind: Тип владельца: ``"core"`` либо ``"plugin"``.
        path: Путь файла-источника относительно корня репозитория.
        lineno: Строка регистрации в файле.
        payload_model: Модель валидации payload (или ``None``).
        capabilities: Capability, заявленные владельцем для action'а.

    """

    action: str
    owner: str
    kind: str
    path: str
    lineno: int
    payload_model: str | None = None
    capabilities: tuple[str, ...] = ()

    @property
    def location(self) -> str:
        """Человекочитаемое место регистрации ``путь:строка``."""
        return f"{self.path}:{self.lineno}"


@dataclass(frozen=True, slots=True)
class Finding:
    """Находка гейта.

    Attributes:
        code: Машиночитаемый код находки.
        action: Action, к которому относится находка.
        message: Текст находки.
        locations: Места, породившие находку.

    """

    code: str
    action: str
    message: str
    locations: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Представить находку для JSON-вывода.

        Returns:
            Словарь с полями находки.

        """
        return {
            "code": self.code,
            "action": self.action,
            "message": self.message,
            "locations": list(self.locations),
        }


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Манифест плагина (``plugin.toml``) в виде, нужном гейту.

    Attributes:
        name: Имя плагина.
        path: Путь манифеста относительно корня репозитория.
        actions: Action'ы, объявленные в ``provides.actions``.
        capabilities: Имена capability, объявленные в ``[[capabilities]]``.

    """

    name: str
    path: str
    actions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()


def _relative_path(path: Path) -> str:
    """Путь относительно корня репозитория (для стабильных отчётов)."""
    try:
        return path.resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Итерировать по ``*.py`` внутри корня без ``__pycache__``."""
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _parse_file(path: Path, errors: list[str]) -> ast.Module | None:
    """Разобрать файл; при ошибке — записать её и вернуть ``None``.

    Args:
        path: Путь к Python-файлу.
        errors: Список ошибок сканирования (накапливается).

    Returns:
        Разобранное AST либо ``None``, если файл не читается/не парсится.

    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{_relative_path(path)}: не удалось прочитать файл: {exc}")
        return None
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        errors.append(
            f"{_relative_path(path)}: не удалось разобрать AST: {exc.msg} "
            f"(line {exc.lineno})"
        )
        return None


def _literal_str(node: ast.AST | None) -> str | None:
    """Строковый литерал из AST-узла (иначе ``None``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword_value(call: ast.Call, name: str) -> ast.expr | None:
    """Значение keyword-аргумента вызова (иначе ``None``)."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _payload_model_text(node: ast.expr | None) -> str | None:
    """Текст модели payload (``None`` — модель не задана)."""
    if node is None:
        return None
    text = ast.unparse(node).strip()
    if text == "None":
        return None
    return text


def _is_core_registry(node: ast.AST) -> bool:
    """Проверить, что обращение идёт к глобальному реестру actions ядра."""
    return isinstance(node, ast.Name) and node.id.endswith("action_handler_registry")


def _called_name(call: ast.Call) -> str:
    """Имя вызываемой функции (``register`` / ``_register_crud_actions`` …)."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _crud_methods() -> tuple[str, ...]:
    """CRUD-методы, регистрируемые ``_register_crud_actions``.

    Список берётся из исходника ``src/backend/dsl/service_dsl.py`` (AST) —
    гейт не должен расходиться с рантаймом. Если исходник недоступен или
    не разобран — используется константа-fallback.

    Returns:
        Кортеж имён CRUD-методов.

    """
    if not _CRUD_METHODS_SOURCE.exists():
        return _FALLBACK_CRUD_METHODS
    errors: list[str] = []
    tree = _parse_file(_CRUD_METHODS_SOURCE, errors)
    if tree is None:
        return _FALLBACK_CRUD_METHODS
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
        )
        if not any(
            isinstance(target, ast.Name) and target.id == "_CRUD_METHODS"
            for target in targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError, TypeError, SyntaxError:
            return _FALLBACK_CRUD_METHODS
        if isinstance(value, tuple | list) and all(
            isinstance(item, str) for item in value
        ):
            return tuple(value)
    return _FALLBACK_CRUD_METHODS


def _core_claim(
    action: str, *, path: str, lineno: int, payload_model: str | None = None
) -> ActionClaim:
    """Собрать claim ядра."""
    return ActionClaim(
        action=action,
        owner=_CORE_OWNER,
        kind="core",
        path=path,
        lineno=lineno,
        payload_model=payload_model,
    )


def _register_claims(call: ast.Call, path: str) -> list[ActionClaim]:
    """Claims из ``action_handler_registry.register(action=..., ...)``."""
    action = _literal_str(_keyword_value(call, "action"))
    if action is None:
        return []
    payload = _payload_model_text(_keyword_value(call, "payload_model"))
    return [_core_claim(action, path=path, lineno=call.lineno, payload_model=payload)]


def _register_many_claims(call: ast.Call, path: str) -> list[ActionClaim]:
    """Claims из ``action_handler_registry.register_many([ActionHandlerSpec(...)])``."""
    if not call.args:
        return []
    container = call.args[0]
    if not isinstance(container, ast.List | ast.Tuple):
        return []
    claims: list[ActionClaim] = []
    for element in container.elts:
        if not isinstance(element, ast.Call):
            continue
        if _called_name(element) != "ActionHandlerSpec":
            continue
        action = _literal_str(_keyword_value(element, "action"))
        if action is None:
            continue
        payload = _payload_model_text(_keyword_value(element, "payload_model"))
        claims.append(
            _core_claim(action, path=path, lineno=element.lineno, payload_model=payload)
        )
    return claims


def _register_metadata_claims(call: ast.Call, path: str) -> list[ActionClaim]:
    """Claims из ``register_with_metadata(action=..., metadata=ActionMetadata(...))``."""
    action = _literal_str(_keyword_value(call, "action"))
    if action is None:
        return []
    payload: str | None = None
    metadata = _keyword_value(call, "metadata")
    if isinstance(metadata, ast.Call):
        payload = _payload_model_text(_keyword_value(metadata, "input_model"))
    return [_core_claim(action, path=path, lineno=call.lineno, payload_model=payload)]


def _crud_claims(
    call: ast.Call, path: str, crud_methods: Sequence[str]
) -> list[ActionClaim]:
    """Claims из ``_register_crud_actions("domain", ...)``."""
    if not call.args:
        return []
    prefix = _literal_str(call.args[0])
    if prefix is None:
        return []
    return [
        _core_claim(f"{prefix}.{method}", path=path, lineno=call.lineno)
        for method in crud_methods
    ]


def _scan_core(
    root: Path, crud_methods: Sequence[str], errors: list[str]
) -> list[ActionClaim]:
    """Собрать claims ядра из канонического пакета регистрации actions.

    Args:
        root: Корень сканирования (обычно ``src/backend/dsl/commands/setup``).
        crud_methods: CRUD-методы для ``_register_crud_actions``.
        errors: Список ошибок сканирования (накапливается).

    Returns:
        Список claims ядра.

    """
    claims: list[ActionClaim] = []
    for path in _iter_python_files(root):
        tree = _parse_file(path, errors)
        if tree is None:
            continue
        rel = _relative_path(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _called_name(node) == "_register_crud_actions":
                claims.extend(_crud_claims(node, rel, crud_methods))
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not _is_core_registry(node.func.value):
                continue
            if node.func.attr == "register":
                claims.extend(_register_claims(node, rel))
            elif node.func.attr == "register_many":
                claims.extend(_register_many_claims(node, rel))
            elif node.func.attr == "register_with_metadata":
                claims.extend(_register_metadata_claims(node, rel))
    return claims


def scan_manifests(root: Path) -> tuple[list[PluginManifest], list[str]]:
    """Собрать манифесты плагинов (``plugin.toml``).

    Args:
        root: Корень расширений.

    Returns:
        Пара ``(манифесты, ошибки сканирования)``.

    """
    manifests: list[PluginManifest] = []
    errors: list[str] = []
    if not root.exists():
        return manifests, [f"{root}: каталог расширений не найден"]
    for path in sorted(root.rglob("plugin.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{_relative_path(path)}: не удалось разобрать TOML: {exc}")
            continue
        provides = data.get("provides")
        actions: tuple[str, ...] = ()
        if isinstance(provides, dict):
            raw_actions = provides.get("actions")
            if isinstance(raw_actions, list):
                actions = tuple(str(item) for item in raw_actions)
        capabilities = tuple(
            sorted(
                {
                    str(entry.get("name"))
                    for entry in (data.get("capabilities") or [])
                    if isinstance(entry, dict) and entry.get("name")
                }
            )
        )
        manifests.append(
            PluginManifest(
                name=str(data.get("name") or path.parent.name),
                path=_relative_path(path),
                actions=actions,
                capabilities=capabilities,
            )
        )
    return manifests, errors


def _plugin_name(path: Path, manifests_by_path: dict[str, PluginManifest]) -> str:
    """Имя плагина для ``plugin.py`` (из манифеста или по каталогу)."""
    manifest = manifests_by_path.get(_relative_path(path.parent / "plugin.toml"))
    if manifest is not None:
        return manifest.name
    return path.parent.name


def _metadata_input_model(call: ast.Call) -> str | None:
    """``input_model`` из ``spec=ActionMetadata(...)`` (иначе ``None``)."""
    spec = _keyword_value(call, "spec")
    if not isinstance(spec, ast.Call):
        return None
    return _payload_model_text(_keyword_value(spec, "input_model"))


def _scan_plugins(
    root: Path, manifests: Sequence[PluginManifest], errors: list[str]
) -> list[ActionClaim]:
    """Собрать claims плагинов из хука ``on_register_actions``.

    Args:
        root: Корень расширений.
        manifests: Манифесты плагинов (для capability-контекста).
        errors: Список ошибок сканирования (накапливается).

    Returns:
        Список claims плагинов.

    """
    by_path = {manifest.path: manifest for manifest in manifests}
    by_name = {manifest.name: manifest for manifest in manifests}
    claims: list[ActionClaim] = []
    for path in sorted(root.rglob("plugin.py")):
        tree = _parse_file(path, errors)
        if tree is None:
            continue
        rel = _relative_path(path)
        plugin_name = _plugin_name(path, by_path)
        capabilities = (
            by_name[plugin_name].capabilities if plugin_name in by_name else ()
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name != _PLUGIN_HOOK:
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                if not isinstance(call.func, ast.Attribute):
                    continue
                if call.func.attr != "register":
                    continue
                if _is_core_registry(call.func.value):
                    continue
                if not call.args:
                    continue
                action = _literal_str(call.args[0])
                if action is None:
                    continue
                claims.append(
                    ActionClaim(
                        action=action,
                        owner=plugin_name,
                        kind="plugin",
                        path=rel,
                        lineno=call.lineno,
                        payload_model=_metadata_input_model(call),
                        capabilities=capabilities,
                    )
                )
    return claims


def scan_claims(
    core_root: Path, extensions_root: Path
) -> tuple[list[ActionClaim], list[PluginManifest], list[str]]:
    """Собрать все claims (ядро + плагины) и манифесты.

    Args:
        core_root: Корень регистрации actions ядра.
        extensions_root: Корень расширений.

    Returns:
        Тройка ``(claims, манифесты, ошибки сканирования)``.

    """
    errors: list[str] = []
    manifests, manifest_errors = scan_manifests(extensions_root)
    errors.extend(manifest_errors)
    crud_methods = _crud_methods()
    claims = _scan_core(core_root, crud_methods, errors)
    claims.extend(_scan_plugins(extensions_root, manifests, errors))
    return claims, manifests, errors


def check_ownership(
    claims: Sequence[ActionClaim], manifests: Sequence[PluginManifest]
) -> tuple[list[Finding], list[Finding]]:
    """Проверить владение actions.

    Args:
        claims: Собранные регистрации.
        manifests: Манифесты плагинов.

    Returns:
        Пара ``(нарушения, мягкие находки)``.

    """
    by_action: dict[str, list[ActionClaim]] = {}
    for claim in claims:
        by_action.setdefault(claim.action, []).append(claim)

    violations: list[Finding] = []
    warnings: list[Finding] = []

    for action, group in sorted(by_action.items()):
        locations = tuple(claim.location for claim in group)
        if len(group) > 1:
            owner_names = ", ".join(sorted({claim.owner for claim in group}))
            violations.append(
                Finding(
                    code="duplicate_owner",
                    action=action,
                    message=(
                        f"action зарегистрирован в {len(group)} местах "
                        f"({owner_names}) — владелец должен быть один"
                    ),
                    locations=locations,
                )
            )
        models = {claim.payload_model for claim in group}
        if len(models) > 1:
            rendered = ", ".join(sorted(str(model) for model in models))
            violations.append(
                Finding(
                    code="payload_model_mismatch",
                    action=action,
                    message=f"расхождение payload_model между владельцами: {rendered}",
                    locations=locations,
                )
            )
        capability_sets = {claim.capabilities for claim in group}
        if len(capability_sets) > 1:
            rendered = " | ".join(
                ", ".join(sorted(caps)) if caps else "<пусто>"
                for caps in sorted(capability_sets)
            )
            violations.append(
                Finding(
                    code="capability_mismatch",
                    action=action,
                    message=f"расхождение capability между владельцами: {rendered}",
                    locations=locations,
                )
            )

    declared: dict[str, list[PluginManifest]] = {}
    for manifest in manifests:
        for action in manifest.actions:
            declared.setdefault(action, []).append(manifest)

    for action, manifest_owners in sorted(declared.items()):
        if len(manifest_owners) > 1:
            names = ", ".join(sorted(owner.name for owner in manifest_owners))
            violations.append(
                Finding(
                    code="manifest_conflict",
                    action=action,
                    message=f"action объявлен в нескольких манифестах: {names}",
                    locations=tuple(owner.path for owner in manifest_owners),
                )
            )
        elif action not in by_action:
            warnings.append(
                Finding(
                    code="unregistered_action",
                    action=action,
                    message=(
                        f"объявлен в манифесте {manifest_owners[0].name}, "
                        "но нигде не зарегистрирован"
                    ),
                    locations=(manifest_owners[0].path,),
                )
            )

    manifests_by_name = {manifest.name: manifest for manifest in manifests}
    for claim in claims:
        if claim.kind != "plugin":
            continue
        manifest = manifests_by_name.get(claim.owner)
        if manifest is None:
            warnings.append(
                Finding(
                    code="undeclared_plugin_action",
                    action=claim.action,
                    message=f"плагин {claim.owner} не имеет манифеста plugin.toml",
                    locations=(claim.location,),
                )
            )
        elif claim.action not in manifest.actions:
            warnings.append(
                Finding(
                    code="undeclared_plugin_action",
                    action=claim.action,
                    message=(
                        f"плагин {claim.owner} регистрирует action, "
                        "не объявленный в provides.actions"
                    ),
                    locations=(claim.location,),
                )
            )

    return violations, warnings


def _build_parser() -> argparse.ArgumentParser:
    """Собрать CLI-парсер гейта."""
    parser = argparse.ArgumentParser(
        description="Гейт владения action-обработчиками: «у action'а один владелец»."
    )
    parser.add_argument(
        "--core-root",
        default=str(DEFAULT_CORE_ROOT),
        help="Каталог регистрации actions ядра.",
    )
    parser.add_argument(
        "--extensions-root",
        default=str(DEFAULT_EXTENSIONS_ROOT),
        help="Каталог расширений (плагины + манифесты).",
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON-вывод для CI-интеграции."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Мягкие находки (инвентарь манифестов) тоже блокируют.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа гейта.

    Args:
        argv: Аргументы CLI (по умолчанию — ``sys.argv[1:]``).

    Returns:
        0 — нарушений нет; 1 — нарушения найдены; 2 — ошибка сканирования.

    """
    args = _build_parser().parse_args(argv)
    core_root = Path(args.core_root)
    extensions_root = Path(args.extensions_root)
    missing = [path for path in (core_root, extensions_root) if not path.exists()]
    if missing:
        print(
            "[check_action_ownership] каталоги не найдены: "
            + ", ".join(path.as_posix() for path in missing),
            file=sys.stderr,
        )
        return 2

    claims, manifests, errors = scan_claims(core_root, extensions_root)
    if errors:
        print(
            "[check_action_ownership] FAIL-CLOSED: "
            f"{len(errors)} ошибок(ки) сканирования — результат неполон:",
            file=sys.stderr,
        )
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 2

    violations, warnings = check_ownership(claims, manifests)
    blocking = violations + (warnings if args.strict else [])

    if args.json:
        owners: dict[str, list[str]] = {}
        for claim in claims:
            owners.setdefault(claim.action, [])
            if claim.owner not in owners[claim.action]:
                owners[claim.action].append(claim.owner)
        payload = {
            "total_actions": len(owners),
            "total_claims": len(claims),
            "plugins": len(manifests),
            "strict": bool(args.strict),
            "violations": [finding.as_dict() for finding in violations],
            "warnings": [finding.as_dict() for finding in warnings],
            "owners": {
                action: sorted(value) for action, value in sorted(owners.items())
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if blocking else 0

    if violations:
        print(f"НОВЫЕ нарушения владения actions: {len(violations)}")
        for finding in violations:
            print(f"  [{finding.code}] {finding.action}: {finding.message}")
            for location in finding.locations:
                print(f"      {location}")
    if warnings:
        if args.strict:
            print(f"Мягкие находки (--strict): {len(warnings)}")
        else:
            print(f"Мягкие находки (не блокируют): {len(warnings)}")
        for finding in warnings:
            print(f"  [{finding.code}] {finding.action}: {finding.message}")
            for location in finding.locations:
                print(f"      {location}")

    if blocking:
        return 1

    print(
        f"Владение actions: OK (actions: {len({claim.action for claim in claims})}; "
        f"регистраций: {len(claims)}; плагинов: {len(manifests)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
