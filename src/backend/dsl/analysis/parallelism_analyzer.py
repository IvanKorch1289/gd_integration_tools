"""DAG-анализ DSL-маршрута: поиск параллелизуемых шагов (S13 K2 W3, PERF-6.8).

Строит граф зависимостей между шагами (по data-flow ``body.*`` / ``header.*``
/ ``property.*`` references), выполняет топологическую сортировку и определяет
группы взаимно-независимых шагов, которые можно вынести в ``.parallel({...})``.

Результат — :class:`ParallelismReport` с:

* parallel_groups: списки StepId, которые можно выполнять параллельно;
* critical_path: последовательность шагов на critical path;
* suggested_optimizations: hints для linter ("steps 3,5,7 → .parallel(...)");
* estimated_speedup: оценка по Amdahl's law.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ("Hint", "ParallelismAnalyzer", "ParallelismReport", "StepDependency")

_REF_PATTERN = re.compile(
    r"\$\{(body|header|property)\.([^}]+)\}|\b(body|header|property)\.([a-zA-Z0-9_.]+)"
)


@dataclass(frozen=True, slots=True)
class StepDependency:
    """Зависимость одного шага от другого через data-flow."""

    from_step: str
    to_step: str
    via: str  # "body.x" / "header.y" / "property.z"


@dataclass(frozen=True, slots=True)
class Hint:
    """Рекомендация оптимизации."""

    rule: str  # "LR-PAR-001" и т.п.
    severity: str  # "info" | "warning"
    message: str
    affected_steps: tuple[str, ...]


@dataclass(slots=True)
class ParallelismReport:
    """Результат анализа параллелизма маршрута."""

    parallel_groups: list[list[str]] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    suggested_optimizations: list[Hint] = field(default_factory=list)
    estimated_speedup: float = 1.0
    total_steps: int = 0
    dependencies: list[StepDependency] = field(default_factory=list)


class ParallelismAnalyzer:
    """Статический анализатор DAG-параллелизма (S13 K2 W3)."""

    def analyze(self, steps: list[dict[str, Any]]) -> ParallelismReport:
        """Анализирует список шагов route.toml.

        Args:
            steps: Список dict-описаний шагов (``{"type": "...", "id": "...", ...}``).

        Returns:
            :class:`ParallelismReport` с метриками и hints.
        """
        if not steps:
            return ParallelismReport()

        step_ids = [self._step_id(s, i) for i, s in enumerate(steps)]
        produces, consumes = self._extract_data_flow(steps, step_ids)
        deps = self._build_dependencies(step_ids, produces, consumes)
        groups = self._topological_groups(step_ids, deps)
        critical = self._find_critical_path(step_ids, deps)
        speedup = self._estimate_speedup(step_ids, groups)
        hints = self._build_hints(groups, step_ids)

        return ParallelismReport(
            parallel_groups=groups,
            critical_path=critical,
            suggested_optimizations=hints,
            estimated_speedup=speedup,
            total_steps=len(step_ids),
            dependencies=deps,
        )

    @staticmethod
    def _step_id(step: dict[str, Any], idx: int) -> str:
        if "id" in step:
            return str(step["id"])
        step_type = step.get("type", f"step_{idx}")
        return f"{step_type}#{idx}"

    def _extract_data_flow(
        self, steps: list[dict[str, Any]], step_ids: list[str]
    ) -> tuple[dict[str, str], dict[str, set[str]]]:
        """Возвращает (produces, consumes):

        * produces[reference] = step_id, который последним пишет в reference;
        * consumes[step_id] = set references, которые этот шаг читает.
        """
        produces: dict[str, str] = {}
        consumes: dict[str, set[str]] = {sid: set() for sid in step_ids}
        for step, sid in zip(steps, step_ids):
            # consumes: ищем references в string значениях step.
            for value in self._iter_values(step):
                for ref in self._extract_refs(value):
                    consumes[sid].add(ref)
            # produces: явные target-поля (to / property / inject_as).
            for target_key in ("to", "property", "inject_as"):
                target = step.get(target_key)
                if isinstance(target, str):
                    produces[target] = sid
        return produces, consumes

    @staticmethod
    def _iter_values(obj: Any):
        if isinstance(obj, dict):
            for v in obj.values():
                yield from ParallelismAnalyzer._iter_values(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                yield from ParallelismAnalyzer._iter_values(v)
        elif isinstance(obj, str):
            yield obj

    @staticmethod
    def _extract_refs(value: str) -> set[str]:
        refs: set[str] = set()
        for m in _REF_PATTERN.finditer(value):
            scope = m.group(1) or m.group(3)
            path = m.group(2) or m.group(4)
            if scope and path:
                refs.add(f"{scope}.{path}")
        return refs

    def _build_dependencies(
        self,
        step_ids: list[str],
        produces: dict[str, str],
        consumes: dict[str, set[str]],
    ) -> list[StepDependency]:
        deps: list[StepDependency] = []
        for sid in step_ids:
            for ref in consumes[sid]:
                if ref in produces and produces[ref] != sid:
                    deps.append(
                        StepDependency(from_step=produces[ref], to_step=sid, via=ref)
                    )
        return deps

    def _topological_groups(
        self, step_ids: list[str], deps: list[StepDependency]
    ) -> list[list[str]]:
        """Группы шагов одного "уровня" — взаимно-независимые."""
        # Граф: incoming[step_id] = set parents.
        incoming: dict[str, set[str]] = {sid: set() for sid in step_ids}
        for d in deps:
            incoming[d.to_step].add(d.from_step)

        levels: list[list[str]] = []
        remaining: set[str] = set(step_ids)
        while remaining:
            ready = [sid for sid in remaining if not (incoming[sid] & remaining)]
            if not ready:
                # Цикл; не должно происходить для валидных route DSL.
                ready = sorted(remaining)
            levels.append(ready)
            remaining -= set(ready)
        return levels

    def _find_critical_path(
        self, step_ids: list[str], deps: list[StepDependency]
    ) -> list[str]:
        # Простейшая эвристика: путь через шаги с максимальным in-degree.
        if not deps:
            return list(step_ids)
        in_degree: dict[str, int] = {sid: 0 for sid in step_ids}
        for d in deps:
            in_degree[d.to_step] += 1
        return [sid for sid in step_ids if in_degree[sid] > 0] or list(step_ids)

    def _estimate_speedup(self, step_ids: list[str], groups: list[list[str]]) -> float:
        """Amdahl's law approximation: speedup = N / max_group_size."""
        if not step_ids or not groups:
            return 1.0
        total = len(step_ids)
        # Максимально возможная параллелизация = sequential_length / total_levels.
        sequential = len(groups)
        if sequential == 0:
            return 1.0
        return round(total / sequential, 2)

    def _build_hints(self, groups: list[list[str]], step_ids: list[str]) -> list[Hint]:
        hints: list[Hint] = []
        # LR-PAR-001: если есть group размером >1 — можно использовать .parallel.
        for level_idx, group in enumerate(groups):
            if len(group) > 1:
                hints.append(
                    Hint(
                        rule="LR-PAR-001",
                        severity="info",
                        message=(
                            f"Steps {', '.join(group)} могут выполняться "
                            f".parallel(...) — независимы по data-flow"
                        ),
                        affected_steps=tuple(group),
                    )
                )
        # LR-PAR-002: если все шаги последовательны — нет параллелизма.
        if len(step_ids) > 3 and all(len(g) == 1 for g in groups):
            hints.append(
                Hint(
                    rule="LR-PAR-002",
                    severity="info",
                    message="Route полностью последовательный — возможно нет параллелизуемых шагов",
                    affected_steps=tuple(step_ids),
                )
            )
        return hints
