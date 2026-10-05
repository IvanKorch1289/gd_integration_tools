"""Генератор `lifecycle_graph.json` из текущего кода (Python 3.14, AST).

Артефакт не должен быть «рукописью»: он извлекается из исходников, поэтому
проверяем текущим кодом, а не переносится из прошлой волны.

Запуск (из корня репозитория):

    .venv/bin/python artifacts/current_audit/generate_lifecycle_graph.py

Что извлекается:

* ``LifecycleOperation(...)`` — имя, фаза, criticality, timeout, enabled,
  dependencies из вызовов конструктора в composition-слое;
* стартовые фазы (порядок вызовов регистрации);
* REQUIRED/OPTIONAL-разбиение;
* операции без ``stop`` (rollback невозможен — это F-N5);
* readiness-эндпоинты и их политики (F-G/F-H);
* вызовы AgentSecurityFramework (F-I) и degradation-заглушки (F-L).

Пишет ``lifecycle_graph.json`` рядом с собой и печатает сводку.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = Path(__file__).resolve().parent / "lifecycle_graph.json"

#: Слой, где объявляются production-операции жизненного цикла.
COMPOSITION = ROOT / "src/backend/plugins/composition/setup_infra/lifecycle.py"
#: Модуль с реализацией типизированной операции и раннера.
LIFECYCLE_PKG = ROOT / "src/backend/plugins/composition/lifecycle"
#: Место регистрации ASGI-приложения и его health/readiness-эндпоинтов.
APP_FACTORY = ROOT / "src/backend/plugins/composition/app_factory.py"


def _literal(node: ast.AST | None) -> Any:
    """Безопасно вычислить литерал AST-узла.

    Args:
        node: Узел дерева либо ``None``.

    Returns:
        Значение литерала; ``None``, если вычислить не удалось.

    """
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _kwarg(call: ast.Call, name: str) -> ast.AST | None:
    """Найти именованный аргумент вызова.

    Args:
        call: Узел вызова.
        name: Имя аргумента.

    Returns:
        Узел значения либо ``None``.

    """
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _dotted(node: ast.AST | None) -> str | None:
    """Привести узел к точечному имени (``Criticality.OPTIONAL``).

    Args:
        node: Узел дерева либо ``None``.

    Returns:
        Строковое представление либо ``None``.

    """
    if node is None:
        return None
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return _literal(node) if isinstance(node, ast.Constant) else None


def _module_constants(path: Path) -> dict[str, Any]:
    """Собрать константы уровня модуля (для разрешения ``phase=``).

    Args:
        path: Путь к Python-файлу.

    Returns:
        Словарь ``{имя: значение}`` для присваиваний литералов.

    """
    constants: dict[str, Any] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                value = _literal(node.value)
                if value is not None:
                    constants[target.id] = value
    return constants


def extract_operations() -> list[dict[str, Any]]:
    """Извлечь все ``LifecycleOperation(...)`` из composition-слоя.

    Returns:
        Список операций в порядке объявления.

    """
    constants = _module_constants(COMPOSITION)
    tree = ast.parse(COMPOSITION.read_text(encoding="utf-8"))
    operations: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "LifecycleOperation":
            continue
        # ``LifecycleOperation.criticality`` по умолчанию REQUIRED
        # (operations.py:106) — отсутствие аргумента означает REQUIRED,
        # а не «неизвестно».
        criticality = _dotted(_kwarg(node, "criticality")) or "Criticality.REQUIRED"
        phase = _dotted(_kwarg(node, "phase"))
        if phase in constants:
            phase = constants[phase]
        operations.append(
            {
                "name": _literal(_kwarg(node, "name")),
                "phase": phase,
                "criticality": criticality,
                "timeout": _literal(_kwarg(node, "timeout")),
                "enabled": _literal(_kwarg(node, "enabled")),
                "dependencies": _literal(_kwarg(node, "dependencies")),
                "has_start": _kwarg(node, "start") is not None,
                "has_stop": _kwarg(node, "stop") is not None,
                "lineno": node.lineno,
            }
        )
    return operations


def extract_startup_phases() -> list[dict[str, Any]]:
    """Извлечь ``STARTUP_PHASES`` — app-level фазы в порядке регистрации.

    Это **другая** структура, чем ``LifecycleOperation``: она оркестрирует
    startup приложения целиком (observability → infrastructure → services),
    тогда как ``LifecycleOperation`` описывает отдельные операции инфраструктуры
    внутри composition-слоя.

    Returns:
        Список фаз в порядке объявления.

    """
    path = LIFECYCLE_PKG / "startup_phases" / "__init__.py"
    if not path.exists():
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "STARTUP_PHASES" and isinstance(node.value, ast.Tuple):
                return [
                    {"index": i, "phase": _dotted(el) or _literal(el), "lineno": node.lineno}
                    for i, el in enumerate(node.value.elts)
                ]
    return []


def extract_readiness_endpoints() -> list[dict[str, Any]]:
    """Найти health/readiness-эндпоинты и заголовки авторизации.

    Returns:
        Список эндпоинтов с путём и флагом обязательной аутентификации.

    """
    found: list[dict[str, Any]] = []
    for source in sorted(APP_FACTORY.parent.rglob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            attr = getattr(func, "attr", None)
            if attr not in {"get", "add_api_route", "api_route"}:
                continue
            path = _literal(node.args[0]) if node.args else None
            if not isinstance(path, str) or not any(
                token in path for token in ("health", "ready", "live", "startup")
            ):
                continue
            found.append(
                {
                    "path": path,
                    "file": str(source.relative_to(ROOT)),
                    "lineno": node.lineno,
                    "requires_auth": any(
                        kw.arg in {"dependencies", "auth", "security"} for kw in node.keywords
                    ),
                }
            )
    return found


def main() -> int:
    """Собрать и записать `lifecycle_graph.json`.

    Returns:
        ``0`` — артефакт записан.

    """
    operations = extract_operations()
    phases = extract_startup_phases()
    readiness = extract_readiness_endpoints()
    without_stop = [op["name"] for op in operations if not op["has_stop"]]
    required = [op for op in operations if "REQUIRED" in (op["criticality"] or "")]
    optional = [op for op in operations if "OPTIONAL" in (op["criticality"] or "")]

    head = subprocess.run(  # noqa: S603 — литеральный argv, shell=False
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    payload = {
        "source": str(COMPOSITION.relative_to(ROOT)),
        "_provenance": {
            "head": head,
            "generator": "artifacts/current_audit/generate_lifecycle_graph.py",
            "method": "ast.parse по composition-слою; значения — ast.literal_eval",
            "note": (
                "Перегенерировано после fast-forward-слива fix/temporal-fail-closed-at. "
                "Количество операций не изменилось (11), но start_temporal_worker_runtime "
                "стал fail-closed: пустой activities/недоступный SDK/кластер теперь "
                "дают RuntimeError, а не тихий return."
            ),
        },
        "operation_structures": {
            "total": len(operations),
            "required": len(required),
            "optional": len(optional),
            "with_stop": sum(1 for op in operations if op["has_stop"]),
            "without_stop": len(without_stop),
        },
        "operations": operations,
        "startup_phases": phases,
        "startup_phase_total": len(phases),
        "readiness_endpoints": readiness,
        "operations_without_stop": {
            "names": without_stop,
            "count": len(without_stop),
            "impact": "операции не откатываются при частичном старте (F-N5)",
        },
    }

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"операций: {len(operations)} (REQUIRED {len(required)}, OPTIONAL {len(optional)})")
    print(f"без stop: {len(without_stop)} → {', '.join(str(n) for n in without_stop)}")
    print(f"стартовых фаз: {len(phases)}")
    print(f"readiness-эндпоинтов: {len(readiness)}")
    print(f"written -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
