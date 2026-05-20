"""Route flow renderer — Mermaid/BPMN/SVG для DSL routes (S10 K3 W9, DOC-7.3).

Превращает YAML/TOML route в визуальное представление потока:

* ``mermaid`` (default) — Mermaid flowchart syntax (можно вставлять в
  Markdown, GitLab/GitHub render);
* ``bpmn`` — упрощённое BPMN 2.0 XML (для импорта в BPMN-редакторы);
* ``svg`` — SVG-эскиз (требует graphviz).

Запуск:

.. code-block:: bash

    python tools/dsl_render.py routes/my_route/main.dsl.yaml \
        --format mermaid > docs/generated/my_route.mmd

    python manage.py dsl render ROUTE=my_route --format bpmn
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

__all__ = ("render", "render_mermaid", "render_bpmn", "Format")

Format = str  # Literal["mermaid", "bpmn", "svg"]


def _slug(text: str) -> str:
    """Безопасный node-id для Mermaid (без пробелов и спец-символов)."""
    return "".join(c if c.isalnum() else "_" for c in text)[:32] or "n"


def _step_label(step: Any, idx: int) -> str:
    """Лейбл для шага (тип + key)."""
    if not isinstance(step, dict):
        return f"step_{idx}: {step!r}"
    if len(step) == 1:
        return next(iter(step.keys()))
    return ",".join(step.keys())


def render_mermaid(route: dict) -> str:
    """Возвращает Mermaid flowchart как строку."""
    lines = ["flowchart TD"]
    lines.append(f"  start([Source: {route.get('source', '?')}])")

    steps = route.get("steps") or route.get("processors") or []
    prev = "start"
    for idx, step in enumerate(steps):
        label = _step_label(step, idx)
        node_id = f"s{idx}_{_slug(label)}"
        lines.append(f"  {node_id}[\"{label}\"]")
        lines.append(f"  {prev} --> {node_id}")
        prev = node_id

    target = route.get("to") or route.get("target")
    if target:
        end_id = "end_node"
        lines.append(f"  {end_id}([{_step_label(target, 999)}])")
        lines.append(f"  {prev} --> {end_id}")

    return "\n".join(lines) + "\n"


def render_bpmn(route: dict) -> str:
    """Возвращает упрощённый BPMN 2.0 XML."""
    route_id = route.get("route_id", "route")
    elements: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<bpmn:definitions xmlns:bpmn='
        '"http://www.omg.org/spec/BPMN/20100524/MODEL">',
        f'  <bpmn:process id="{route_id}" isExecutable="true">',
        '    <bpmn:startEvent id="StartEvent_1" '
        f'name="Source: {route.get("source", "?")}" />',
    ]
    prev = "StartEvent_1"
    steps = route.get("steps") or route.get("processors") or []
    for idx, step in enumerate(steps):
        node_id = f"Task_{idx}"
        label = _step_label(step, idx)
        elements.append(
            f'    <bpmn:task id="{node_id}" name="{label}" />'
        )
        elements.append(
            f'    <bpmn:sequenceFlow id="Flow_{idx}" '
            f'sourceRef="{prev}" targetRef="{node_id}" />'
        )
        prev = node_id

    elements.append('    <bpmn:endEvent id="EndEvent_1" />')
    elements.append(
        f'    <bpmn:sequenceFlow id="FlowEnd" sourceRef="{prev}" '
        f'targetRef="EndEvent_1" />'
    )
    elements.append('  </bpmn:process>')
    elements.append('</bpmn:definitions>')
    return "\n".join(elements) + "\n"


def render_svg(route: dict) -> str:
    """Возвращает Mermaid-payload + явный hint про graphviz."""
    return (
        "<!-- SVG render требует graphviz CLI; здесь возвращён mermaid -->\n"
        + render_mermaid(route)
    )


def render(route: dict, fmt: Format = "mermaid") -> str:
    """Унифицированный entry-point."""
    if fmt == "mermaid":
        return render_mermaid(route)
    if fmt == "bpmn":
        return render_bpmn(route)
    if fmt == "svg":
        return render_svg(route)
    raise ValueError(
        f"Unknown format {fmt!r}; ожидается mermaid/bpmn/svg"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DSL route flow renderer")
    parser.add_argument("route_path", type=Path)
    parser.add_argument(
        "--format",
        choices=("mermaid", "bpmn", "svg"),
        default="mermaid",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if not args.route_path.is_file():
        print(f"Файл не найден: {args.route_path}", file=sys.stderr)
        return 2

    route = yaml.safe_load(args.route_path.read_text(encoding="utf-8"))
    if not isinstance(route, dict):
        print("Route YAML root должен быть mapping", file=sys.stderr)
        return 1

    output = render(route, args.format)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f"OK: {args.out}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
