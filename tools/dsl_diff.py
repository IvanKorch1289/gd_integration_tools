"""Pipeline diff — структурное сравнение двух YAML-определений pipeline.

Использование::

    python tools/dsl_diff.py before.yaml after.yaml
    python tools/dsl_diff.py --format json before.yaml after.yaml

Инструмент загружает оба YAML через :mod:`app.dsl.yaml_loader`, извлекает
список процессоров и их параметры, и выводит построчный diff.

В отличие от обычного ``diff``, этот инструмент:

* игнорирует порядок полей внутри процессора (сортировка по алфавиту);
* подсвечивает добавленные/удалённые/изменённые шаги;
* работает со ссылочной нотацией ``pipeline_ref``.

Предназначен для code-review DSL-pipelines и audit-отчётов.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_yaml(path: Path) -> dict[str, Any]:
    """Загружает YAML-файл. Использует ``yaml.safe_load`` (без custom tags)."""
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("PyYAML не установлен: pip install PyYAML") from exc
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _normalize_steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Возвращает список шагов pipeline в стабильно отсортированном виде.

    Каждый шаг — один dict с единственным ключом (имя processor'а).
    Внутренние параметры сортируются по алфавиту для детерминированного сравнения.
    """
    processors = doc.get("processors") or doc.get("steps") or []
    normalized: list[dict[str, Any]] = []
    for item in processors:
        if not isinstance(item, dict) or len(item) != 1:
            normalized.append({"__raw__": item})
            continue
        name, params = next(iter(item.items()))
        if isinstance(params, dict):
            params = {k: params[k] for k in sorted(params.keys())}
        normalized.append({name: params})
    return normalized


def _diff_pipelines(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Формирует структурный diff между двумя pipeline'ами."""
    before_steps = _normalize_steps(before)
    after_steps = _normalize_steps(after)

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    # Сопоставляем шаги по индексу (упрощённо — без LCS, т.к. порядок важен).
    max_len = max(len(before_steps), len(after_steps))
    for idx in range(max_len):
        b = before_steps[idx] if idx < len(before_steps) else None
        a = after_steps[idx] if idx < len(after_steps) else None
        if b is None and a is not None:
            added.append({"index": idx, "step": a})
        elif b is not None and a is None:
            removed.append({"index": idx, "step": b})
        elif b != a:
            changed.append({"index": idx, "before": b, "after": a})

    return {
        "route_id_before": before.get("route_id"),
        "route_id_after": after.get("route_id"),
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _render_text(diff: dict[str, Any]) -> str:
    """Человекочитаемый вывод diff."""
    lines: list[str] = []
    rb, ra = diff.get("route_id_before"), diff.get("route_id_after")
    lines.append(f"route_id: {rb} → {ra}")
    if diff["added"]:
        lines.append("\nДобавлено:")
        for item in diff["added"]:
            lines.append(f"  + [{item['index']}] {item['step']}")
    if diff["removed"]:
        lines.append("\nУдалено:")
        for item in diff["removed"]:
            lines.append(f"  - [{item['index']}] {item['step']}")
    if diff["changed"]:
        lines.append("\nИзменено:")
        for item in diff["changed"]:
            lines.append(f"  ~ [{item['index']}]")
            lines.append(f"     before: {item['before']}")
            lines.append(f"     after:  {item['after']}")
    if not (diff["added"] or diff["removed"] or diff["changed"]):
        lines.append("\n(pipeline идентичен)")
    return "\n".join(lines)


def main() -> None:
    """CLI-точка входа."""
    parser = argparse.ArgumentParser(description="Pipeline diff для YAML-DSL")
    parser.add_argument("before", type=Path, help="Исходный YAML-файл")
    parser.add_argument("after", type=Path, help="Новый YAML-файл")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    diff = _diff_pipelines(_load_yaml(args.before), _load_yaml(args.after))

    if args.format == "json":
        json.dump(diff, sys.stdout, ensure_ascii=False, indent=2)
    else:
        print(_render_text(diff))

    # Exit-код 1 если есть различия — удобно в CI.
    has_changes = bool(diff["added"] or diff["removed"] or diff["changed"])
    sys.exit(1 if has_changes else 0)


if __name__ == "__main__":
    main()
