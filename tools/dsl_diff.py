"""Pipeline diff — структурное сравнение двух YAML-определений pipeline.

S62 W3: мигрирован с ``argparse`` на ``typer`` + ``rich`` (libraries > custom,
per v22 п.5). Сохранены: typer-native entry ``app_main`` + legacy
``main()`` callback для backward-compat.

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

import json
import sys
from pathlib import Path
from typing import Any, Literal

import typer
from rich.console import Console

Format = Literal["text", "json"]
app = typer.Typer(
    name="dsl-diff",
    help="Pipeline diff для YAML-DSL (структурное сравнение двух pipelines).",
    no_args_is_help=True,
    add_completion=False,
)
_console = Console()


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


@app.command(name="diff")
def app_main(
    before: Path = typer.Argument(..., help="Исходный YAML-файл"),
    after: Path = typer.Argument(..., help="Новый YAML-файл"),
    format: Format = typer.Option("text", "--format", help="text | json"),
) -> None:
    """Typer-native entry для pipeline diff."""
    diff = _diff_pipelines(_load_yaml(before), _load_yaml(after))

    if format == "json":
        json.dump(diff, sys.stdout, ensure_ascii=False, indent=2)
    else:
        _console.print(_render_text(diff))

    # Exit-код 1 если есть различия — удобно в CI.
    has_changes = bool(diff["added"] or diff["removed"] or diff["changed"])
    raise typer.Exit(code=1 if has_changes else 0)


def main() -> None:
    """Backward-compat CLI entry (S58 W2 pattern)."""
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        _console.print(f"[bold red][dsl-diff] error:[/bold red] {exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
