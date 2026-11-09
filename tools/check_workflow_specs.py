"""Линтер workflow-спецификаций ``*.workflow.yaml`` (ADR-0433).

Зачем
-----
Шаблоны workflow проверялись только по факту использования: опечатка в имени
activity или невалидное поле шага обнаруживались **в рантайме** (build-time
падал Worker, а в dev-режиме — шаг). Например, шаблон
``guardrail_cost_budget`` падал с ``GuardrailValueTypeError`` уже при запуске.

Линтер делает обе проверки заранее и печатает понятную диагностику
``file:step.field: текст``:

1. **Спека** — ``WorkflowDeclaration.model_validate`` (pydantic) ловит
   невалидные/пропущенные поля шага;
2. **Имена activity** — ``ActivityBridge.collect_activities(validate=True)``
   сверяет имена activity с action-реестром и списком внутренних activity
   (ADR-0398).

Использование::

    python tools/check_workflow_specs.py            # проверка (exit 1 при ошибках)
    python tools/check_workflow_specs.py --report   # печать всех находок
"""

from __future__ import annotations

import argparse
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


def check_spec(path: Path) -> list[str]:
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
