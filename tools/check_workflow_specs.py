"""Линтер workflow-спецификаций ``*.workflow.yaml`` (ADR-0433).

Зачем
-----
Шаблоны workflow проверялись только по факту использования: опечатка в имени
activity или невалидное поле шага обнаруживались **в рантайме** (build-time
падал Worker, а в dev-режиме — шаг). Например, шаблон
``guardrail_cost_budget`` падал с ``GuardrailValueTypeError`` уже при запуске.

Линтер делает все проверки заранее и печатает понятную диагностику
``file:step.field: текст``:

1. **Спека** — ``WorkflowDeclaration.model_validate`` (pydantic) ловит
   невалидные/пропущенные поля шага;
2. **Имена activity** — ``ActivityBridge.collect_activities(validate=True)``
   сверяет имена activity с action-реестром и списком внутренних activity
   (ADR-0398);
3. **Контракт ``call_function``** — шаг ``call_function`` вызывает функцию
   как ``fn(payload)``, где ``payload`` — **словарь**
   (:func:`src.backend.dsl.workflow.compiler.activity_bridge.bridge_call_function`,
   :meth:`src.backend.dsl.engine.processors.function_call.CallFunctionProcessor.process`).
   Если сигнатура функции требует список или скаляр, шаг падает в рантайме
   (или, что хуже, молча считает неверные значения — F-06, волна 35:
   ``estimate_usage(messages: list)`` получала dict и guardrail стоимости
   **никогда не срабатывал**).

Использование::

    python tools/check_workflow_specs.py            # проверка (exit 1 при ошибках)
    python tools/check_workflow_specs.py --report   # печать всех находок
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Any

import yaml

#: Каталоги, где лежат workflow-спецификации.
_SEARCH_ROOTS = (
    Path("src/backend/dsl/workflow/templates"),
    Path("extensions"),
    Path("routes"),
)

#: Корень репозитория — по нему разрешаются модули ``module:fn``.
_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Типы аннотаций, совместимые с payload-словарём (движок передаёт dict).
_DICT_COMPATIBLE_TYPES = frozenset(
    {"Any", "DefaultDict", "Dict", "Mapping", "MutableMapping", "dict", "object"}
)

#: Типы аннотаций, несовместимые с payload-словарём: движок передаёт dict,
#: а функция ждёт список/итератор/скаляр.
_INCOMPATIBLE_TYPES = frozenset(
    {
        "Collection",
        "Decimal",
        "FrozenSet",
        "Generator",
        "Iterable",
        "Iterator",
        "List",
        "MutableSequence",
        "Sequence",
        "Set",
        "Tuple",
        "UUID",
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "date",
        "datetime",
        "float",
        "frozenset",
        "int",
        "list",
        "set",
        "str",
        "timedelta",
        "tuple",
    }
)


def _spec_paths() -> list[Path]:
    """Все ``*.workflow.yaml`` в проекте (дедуплицировано)."""
    found: set[Path] = set()
    for root in _SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.workflow.yaml"):
            found.add(path)
    return sorted(found)


def _step_field(error: Any) -> str:
    """Поле шага из pydantic-ошибки (``steps.0.timeout_s`` → ``step[0]``)."""
    location = getattr(error, "loc", ()) or ()
    parts = [str(part) for part in location]
    if len(parts) >= 2 and parts[0] == "steps":
        return f"step[{parts[1]}]" + (
            f".{'.'.join(parts[2:])}" if len(parts) > 2 else ""
        )
    return ".".join(parts) if parts else "<root>"


def _annotation_type_names(node: ast.expr | None) -> set[str]:
    """Имена базовых типов из аннотации параметра.

    Для ``Union`` (``A | B``) собираются обе ветви; для строковых аннотаций
    (``from __future__ import annotations``) выражение разбирается как Python-код.

    Args:
        node: AST-узел аннотации.

    Returns:
        Множество имён базовых типов.

    """
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Subscript):
        return _annotation_type_names(node.value)
    if isinstance(node, ast.BinOp):
        return _annotation_type_names(node.left) | _annotation_type_names(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            parsed = ast.parse(node.value, mode="eval")
        except SyntaxError:
            return set()
        return _annotation_type_names(parsed.body)
    return set()


def _incompatible_type(names: set[str]) -> str | None:
    """Имя типа, несовместимого с payload-словарём (иначе ``None``)."""
    for name in sorted(names):
        if name in _INCOMPATIBLE_TYPES:
            return name
    return None


def _resolve_module_file(module_name: str, repo_root: Path) -> Path | None:
    """Найти файл модуля по dotted-имени (``.py`` или пакет ``__init__.py``)."""
    relative = module_name.replace(".", "/")
    for candidate in (
        repo_root / f"{relative}.py",
        repo_root / relative / "__init__.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def _find_function(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Найти module-level функцию по имени (``None`` — не найдена)."""
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
        ):
            return node
    return None


def check_call_function_contract(
    ref: str, *, repo_root: Path = _REPO_ROOT
) -> list[str]:
    """Проверить контракт ``fn(payload: dict)`` для ссылки ``module:fn``.

    Args:
        ref: Ссылка вида ``module.path:function_name``.
        repo_root: Корень репозитория (по нему ищется модуль).

    Returns:
        Список находок (пустой — контракт соблюдён или не доказан).

    """
    if ":" not in ref:
        return [f"call_function {ref!r}: ожидается ссылка 'module.path:function_name'"]
    module_name, _, function_name = ref.partition(":")
    module_file = _resolve_module_file(module_name, repo_root)
    if module_file is None:
        return [
            f"call_function {ref!r}: модуль {module_name!r} не найден в репозитории"
        ]
    try:
        tree = ast.parse(
            module_file.read_text(encoding="utf-8"), filename=str(module_file)
        )
    except (OSError, SyntaxError) as exc:
        return [f"call_function {ref!r}: модуль не разобран: {exc}"]
    function = _find_function(tree, function_name)
    if function is None:
        return [f"call_function {ref!r}: функция {function_name!r} не найдена в модуле"]
    positional = [*function.args.posonlyargs, *function.args.args]
    if not positional and function.args.vararg is None:
        return [
            f"call_function {ref!r}: функция не принимает позиционный payload — "
            "движок вызывает fn(payload)"
        ]
    first = positional[0]
    names = _annotation_type_names(first.annotation)
    incompatible = _incompatible_type(names)
    if incompatible is not None:
        return [
            f"call_function {ref!r}: параметр {first.arg!r} требует "
            f"{incompatible}, а движок передаёт dict (fn(payload)) — "
            "нужен адаптер под контракт шага"
        ]
    return []


def check_spec(path: Path, *, repo_root: Path = _REPO_ROOT) -> list[str]:
    """Проверить одну спецификацию; вернуть список находок."""
    findings: list[str] = []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"{path}: YAML не разбирается: {exc}"]
    if not isinstance(raw, dict):
        return [f"{path}: ожидался YAML-mapping"]

    from src.backend.dsl.workflow.spec import WorkflowDeclaration

    try:
        declaration = WorkflowDeclaration.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — pydantic/ValueError
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for error in errors():
                findings.append(
                    f"{path}:{_step_field(error)}: {error.get('msg', str(error))}"
                )
        else:
            findings.append(f"{path}: спека невалидна: {exc}")
        return findings

    from src.backend.dsl.commands.action_registry import action_handler_registry
    from src.backend.dsl.commands.setup import register_action_handlers
    from src.backend.dsl.workflow.compiler.activity_bridge import ActivityBridge

    saved = dict(action_handler_registry._handlers)
    register_action_handlers()
    try:
        bridge = ActivityBridge()
        bridge.collect_activities([declaration], validate=True)
    except Exception as exc:  # noqa: BLE001 — UnknownActivityError и пр.
        findings.append(f"{path}: activity: {exc}")
    finally:
        action_handler_registry._handlers.clear()
        action_handler_registry._handlers.update(saved)

    for step in declaration.steps:
        ref = getattr(step, "ref", None)
        if not isinstance(ref, str):
            continue
        findings.extend(
            f"{path}: {finding}"
            for finding in check_call_function_contract(ref, repo_root=repo_root)
        )
    return findings


def check_compiler_activities() -> list[str]:
    """Проверить, что activity, генерируемые компилятором, зарегистрированы.

    Имена ``memory.reflect`` и ``workflow.checkpoint.put`` не встречаются в
    YAML-спеках — их эмитит компилятор шагов. Если activity не зарегистрирована
    в мосте, Temporal Worker её не знает → ``ActivityNotRegisteredError`` в
    рантайме (шаблон «сломан», но ошибка видна только при запуске).
    """
    findings: list[str] = []
    try:
        from src.backend.dsl.workflow.compiler.activity_bridge import (
            INTERNAL_ACTIVITY_NAMES,
        )
    except ImportError as exc:  # pragma: no cover — defensive
        return [f"activity_bridge недоступен: {exc}"]
    for name in ("memory.reflect", "workflow.checkpoint.put"):
        if name not in INTERNAL_ACTIVITY_NAMES:
            findings.append(
                f"compiler activity {name!r} не зарегистрирована в мосте "
                f"(INTERNAL_ACTIVITY_NAMES)"
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    """Точка входа линтера."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    paths = _spec_paths()
    findings: list[str] = check_compiler_activities()
    for path in paths:
        findings.extend(check_spec(path))

    if findings:
        print(
            f"Workflow-спецификаций: найдено проблем — {len(findings)}", file=sys.stderr
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(f"Workflow-спецификации: OK (проверено {len(paths)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
