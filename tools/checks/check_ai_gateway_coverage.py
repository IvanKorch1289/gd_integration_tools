"""CI-gate: проверка, что все LLM-вызовы идут через AIGateway (ADR-NEW-19).

Scaffold Sprint 25 W1 — warn-only mode. Полная реализация
strict-mode — Sprint 27 closure (after AIGateway adapter wrap S25 W3).

Назначение
----------
AST-checker, аналогичный ``check_grep_violations.py`` (S17/K9). Ищет
прямые вызовы LLM в обход :class:`core.ai.gateway.AIGateway`:

* ``litellm.completion()``
* ``litellm.acompletion()``
* ``openai.ChatCompletion.create()``
* ``client.chat.completions.create()``
* ``Agent.run()`` / ``agent.run()`` (PydanticAI)
* ``LangGraphApp.invoke()``

Каждый прямой вызов = violation. Allowlist через
``tools/checks/check_ai_gateway_allowlist.txt``.

Использование
-------------

.. code-block:: bash

    # Warn-only (default S25 W1..S27 W6):
    python tools/checks/check_ai_gateway_coverage.py

    # Strict (S27 closure):
    python tools/checks/check_ai_gateway_coverage.py --strict

Exit codes:

* ``0`` — нет violations (или warn-only).
* ``1`` — strict + найдены violations.

См. docs/adr/0066-ai-gateway-facade.md DoD пункт 7.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# Список прямых LLM-вызовов в обход AIGateway. Каждый — tuple
# ``(qualified_attr_path, description)``.
DIRECT_LLM_CALL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("litellm.completion", "Прямой litellm.completion() — должен быть через AIGateway"),
    (
        "litellm.acompletion",
        "Прямой litellm.acompletion() — должен быть через AIGateway",
    ),
    ("openai.ChatCompletion.create", "Прямой openai.ChatCompletion — устаревший API"),
    (
        "chat.completions.create",
        "Прямой client.chat.completions.create() — должен быть через AIGateway",
    ),
)


@dataclass(frozen=True, slots=True)
class Violation:
    """Найденный прямой LLM-вызов в обход :class:`AIGateway`.

    Attributes:
        file_path: Абсолютный путь к файлу с нарушением.
        line: Номер строки (1-indexed).
        col: Номер колонки.
        pattern: Идентификатор pattern'а из :data:`DIRECT_LLM_CALL_PATTERNS`.
        description: Человекочитаемое описание.
    """

    file_path: Path
    line: int
    col: int
    pattern: str
    description: str


def _attr_chain(node: ast.AST) -> str:
    """Восстановить полную dotted-цепочку из AST.

    Args:
        node: Узел AST (``ast.Attribute``, ``ast.Name``).

    Returns:
        Строка вида ``"litellm.completion"`` или ``"chat.completions.create"``;
        пустая строка для unknown узлов.
    """
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _check_file(path: Path) -> list[Violation]:
    """Найти все прямые LLM-вызовы в одном Python-файле.

    Args:
        path: Путь к ``.py`` файлу.

    Returns:
        Список :class:`Violation`.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attr_chain(node.func)
        for pattern, description in DIRECT_LLM_CALL_PATTERNS:
            if chain.endswith(pattern):
                violations.append(
                    Violation(
                        file_path=path,
                        line=node.lineno,
                        col=node.col_offset,
                        pattern=pattern,
                        description=description,
                    )
                )
                break
    return violations


def _load_allowlist(allowlist_path: Path) -> set[str]:
    """Загрузить allowlist путей, для которых violations игнорируются.

    Args:
        allowlist_path: Путь к файлу со списком (один путь на строку,
            ``#``-комментарии).

    Returns:
        Множество absolute-paths из allowlist.
    """
    if not allowlist_path.exists():
        return set()
    return {
        line.strip()
        for line in allowlist_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def main() -> int:
    """Точка входа CLI.

    Returns:
        ``0`` — нет violations или warn-only.
        ``1`` — strict + найдены violations.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default="src/backend",
        help="Корень поиска .py файлов (default: src/backend).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: exit 1 при violations (default: warn-only).",
    )
    parser.add_argument(
        "--allowlist",
        default="tools/checks/check_ai_gateway_allowlist.txt",
        help="Файл allowlist (default: tools/checks/check_ai_gateway_allowlist.txt).",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    allowlist = _load_allowlist(Path(args.allowlist))

    violations: list[Violation] = []
    for py_file in root.rglob("*.py"):
        rel = py_file.relative_to(root.parent.parent) if root.parent.parent in py_file.parents else py_file
        if str(rel) in allowlist:
            continue
        violations.extend(_check_file(py_file))

    if not violations:
        print("✓ check_ai_gateway_coverage: 0 violations")
        return 0

    print(f"⚠ check_ai_gateway_coverage: {len(violations)} violation(s):")
    for v in violations:
        print(f"  {v.file_path}:{v.line}:{v.col} — {v.pattern}: {v.description}")
    print(
        "\nИсправление: оборачивайте LLM-вызов в core.ai.gateway.AIGateway.invoke()."
    )
    print("Подробности: docs/adr/0066-ai-gateway-facade.md.")

    if args.strict:
        return 1
    print("(warn-only mode; strict ожидается с Sprint 27 closure)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
