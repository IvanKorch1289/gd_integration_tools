"""Визуализация :class:`WorkflowDeclaration` — Sprint 12 K3 W1 + K5 W1.

Public API:

* :func:`to_graphviz` — Graphviz DOT-syntax (для side-by-side diff
  rendering в Streamlit page 31).
* :func:`to_mermaid` — Mermaid ``graph TD`` syntax (для page 33
  templates preview).
* :func:`compute_step_diff` — структурный diff с color-mapping для
  визуализации added/removed/modified.

Контракт V18.1 — отображаемые типы шагов:

* ``activity`` → прямоугольник (rect/box);
* ``saga`` → группа forward+compensate (subgraph);
* ``wait_signal`` → ромб (diamond/rhombus);
* ``sleep`` → круг (oval/circle);
* ``sensor`` → шестигранник (hexagon).

Color-mapping (для diff):

* ``added`` (только в B) → зелёный;
* ``removed`` (только в A) → красный;
* ``modified`` (в обоих, контент отличается) → оранжевый;
* без изменений → дефолтный цвет.

Безопасность:
    DOT/Mermaid escape — двойные кавычки и обратные слэши экранируются
    через простой ``str.replace``. Имена шагов из YAML — trust boundary
    остаётся на загрузке (Pydantic validation в spec.py).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Literal

from src.backend.dsl.workflow.spec import WorkflowDeclaration

__all__ = (
    "ColorMap",
    "StepDiffResult",
    "compute_step_diff",
    "to_graphviz",
    "to_mermaid",
)


DiffStatus = Literal["added", "removed", "modified", "unchanged"]


@dataclass(slots=True, frozen=True)
class StepDiffResult:
    """Структурный diff одного шага между двумя workflow."""

    identity: str
    status: DiffStatus


ColorMap = dict[str, str]
"""Маппинг ``step_identity → color`` для подсветки в графе."""


_GRAPHVIZ_STATUS_COLORS: ColorMap = {
    "added": "green",
    "removed": "red",
    "modified": "orange",
    "unchanged": "black",
}

_MERMAID_STATUS_STYLES: dict[str, str] = {
    "added": "fill:#a8f0a8,stroke:#2e7d32",
    "removed": "fill:#f0a8a8,stroke:#c62828",
    "modified": "fill:#f5d486,stroke:#ef6c00",
    "unchanged": "fill:#ffffff,stroke:#424242",
}


def _step_identity(step: object) -> str:
    """Уникальный идентификатор шага (совпадает с yaml_io._step_identity).

    Дублируется здесь чтобы избежать circular import между yaml_io и
    visualize: yaml_io уже зависит от spec, visualize тоже зависит от
    spec — но не должен зависеть от yaml_io.
    """
    step_type = getattr(step, "type", "unknown")
    if step_type == "activity":
        return f"activity:{step.name}"  # type: ignore[attr-defined]
    if step_type == "saga":
        forward = getattr(step, "forward", [])
        forward_names = ",".join(a.name for a in forward)
        return f"saga:[{forward_names}]"
    if step_type == "wait_signal":
        return f"wait_signal:{step.signal_name}"  # type: ignore[attr-defined]
    if step_type == "sleep":
        return f"sleep:{step.duration_s}"  # type: ignore[attr-defined]
    if step_type == "sensor":
        return f"sensor:{step.predicate}"  # type: ignore[attr-defined]
    return f"{step_type}:unknown"


def _step_label(step: object) -> str:
    """Человекочитаемая надпись для узла графа."""
    step_type = getattr(step, "type", "unknown")
    if step_type == "activity":
        return f"{step.name}\\n(activity)"  # type: ignore[attr-defined]
    if step_type == "saga":
        forward = getattr(step, "forward", [])
        names = ", ".join(a.name for a in forward)
        return f"saga\\n[{names}]"
    if step_type == "wait_signal":
        return f"wait\\n{step.signal_name}"  # type: ignore[attr-defined]
    if step_type == "sleep":
        return f"sleep\\n{step.duration_s}s"  # type: ignore[attr-defined]
    if step_type == "sensor":
        return f"sensor\\n{step.predicate}"  # type: ignore[attr-defined]
    return step_type


def _graphviz_shape(step_type: str) -> str:
    """Форма узла Graphviz по типу шага."""
    return {
        "activity": "box",
        "saga": "folder",
        "wait_signal": "diamond",
        "sleep": "oval",
        "sensor": "hexagon",
    }.get(step_type, "box")


def _mermaid_shape(step_type: str, label: str) -> str:
    """Mermaid-обёртка ``id[label]`` по типу шага."""
    safe_label = label.replace("\\n", "<br/>").replace('"', "'")
    if step_type in {"wait_signal"}:
        return f'{{"{safe_label}"}}'
    if step_type == "sleep":
        return f'(("{safe_label}"))'
    if step_type == "sensor":
        return f'{{{{"{safe_label}"}}}}'
    return f'["{safe_label}"]'


def _escape_dot(value: str) -> str:
    """Escape DOT-strings (двойные кавычки + backslashes)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def to_graphviz(decl: WorkflowDeclaration, *, color_map: ColorMap | None = None) -> str:
    """Сериализовать workflow в Graphviz DOT-source.

    Args:
        decl: Workflow для визуализации.
        color_map: ``step_identity → color`` маппинг для diff-подсветки.
            Если ``None`` — все узлы черные (default).

    Returns:
        DOT-syntax строка, готовая к рендеру через ``graphviz.Source(...)``.
    """
    color_map = color_map or {}
    lines: list[str] = [
        f'digraph "{_escape_dot(decl.name)}" {{',
        "  rankdir=TB;",
        '  node [fontname="Helvetica"];',
        '  edge [fontname="Helvetica"];',
    ]

    node_ids: list[str] = []
    for idx, step in enumerate(decl.steps):
        identity = _step_identity(step)
        node_id = f"n{idx}"
        node_ids.append(node_id)
        label = _step_label(step)
        shape = _graphviz_shape(step.type)
        color = color_map.get(identity, "black")
        lines.append(
            f'  {node_id} [label="{_escape_dot(label)}", shape={shape}, color={color}];'
        )

    for prev, nxt in itertools.pairwise(node_ids):
        lines.append(f"  {prev} -> {nxt};")

    lines.append("}")
    return "\n".join(lines)


def to_mermaid(decl: WorkflowDeclaration, *, color_map: ColorMap | None = None) -> str:
    """Сериализовать workflow в Mermaid ``graph TD`` syntax.

    Args:
        decl: Workflow для визуализации.
        color_map: маппинг ``step_identity → status`` (added/removed/
            modified) для styling через ``classDef``.

    Returns:
        Mermaid ``graph TD`` string, готовый к
        ``streamlit_mermaid.st_mermaid(...)``.
    """
    color_map = color_map or {}
    lines: list[str] = ["graph TD"]
    node_ids: list[str] = []

    for idx, step in enumerate(decl.steps):
        node_id = f"n{idx}"
        node_ids.append(node_id)
        label = _step_label(step)
        shape = _mermaid_shape(step.type, label)
        lines.append(f"    {node_id}{shape}")

    for prev, nxt in itertools.pairwise(node_ids):
        lines.append(f"    {prev} --> {nxt}")

    classes_used: set[str] = set()
    for idx, step in enumerate(decl.steps):
        identity = _step_identity(step)
        status = color_map.get(identity)
        if status and status in _MERMAID_STATUS_STYLES:
            classes_used.add(status)
            lines.append(f"    class n{idx} cls_{status}")

    for status in sorted(classes_used):
        style = _MERMAID_STATUS_STYLES[status]
        lines.append(f"    classDef cls_{status} {style}")

    return "\n".join(lines)


def compute_step_diff(
    decl_a: WorkflowDeclaration, decl_b: WorkflowDeclaration
) -> tuple[list[StepDiffResult], ColorMap, ColorMap]:
    """Структурный diff с готовыми color-map для A и B графов.

    Args:
        decl_a: Базовая (старая) декларация.
        decl_b: Сравниваемая (новая) декларация.

    Returns:
        Tuple ``(diff_results, color_map_a, color_map_b)``:

        * ``diff_results`` — список :class:`StepDiffResult` для всех
          identities, упорядоченный.
        * ``color_map_a`` — раскраска для отображения decl_a:
          removed=red, modified=orange, unchanged=default.
        * ``color_map_b`` — раскраска для отображения decl_b:
          added=green, modified=orange, unchanged=default.
    """
    a_ids = {_step_identity(s): s for s in decl_a.steps}
    b_ids = {_step_identity(s): s for s in decl_b.steps}

    diff_results: list[StepDiffResult] = []
    color_map_a: ColorMap = {}
    color_map_b: ColorMap = {}

    for identity in sorted(set(a_ids) | set(b_ids)):
        in_a = identity in a_ids
        in_b = identity in b_ids
        if in_a and not in_b:
            status: DiffStatus = "removed"
            color_map_a[identity] = _GRAPHVIZ_STATUS_COLORS["removed"]
        elif in_b and not in_a:
            status = "added"
            color_map_b[identity] = _GRAPHVIZ_STATUS_COLORS["added"]
        else:
            if a_ids[identity].model_dump() != b_ids[identity].model_dump():
                status = "modified"
                color_map_a[identity] = _GRAPHVIZ_STATUS_COLORS["modified"]
                color_map_b[identity] = _GRAPHVIZ_STATUS_COLORS["modified"]
            else:
                status = "unchanged"
        diff_results.append(StepDiffResult(identity=identity, status=status))

    return diff_results, color_map_a, color_map_b
