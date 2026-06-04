"""Локальный dry-run executor для DSL routes (S10 K3 W4, DSL-1.5).

Эмулирует выполнение route'а в memory без side-effects:

* парсит YAML/dict;
* проходит по шагам, эмулируя latency (random или per-step hint);
* возвращает список ``StepResult`` для waterfall-визуализации
  (Streamlit/CLI);
* поддерживает sample-payload, который "проходит" через шаги.

Это НЕ реальный pipeline-runtime — настоящий dispatch требует
ProcessorRegistry и Exchange, что доступно только в server-mode.
Dry-run — это "what would happen" для preview.
"""

from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = ("DryRunResult", "StepResult", "dry_run_route")


@dataclass(slots=True)
class StepResult:
    """Один шаг dry-run."""

    index: int
    label: str
    duration_ms: float
    output_preview: str
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DryRunResult:
    """Сводка dry-run."""

    route_id: str | None
    steps: list[StepResult] = field(default_factory=list)
    total_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "total_ms": self.total_ms,
            "steps": [asdict(s) for s in self.steps],
        }


# Эмулируем стандартные latency-классы (мс).
_LATENCY_PROFILE: dict[str, tuple[float, float]] = {
    "http_call": (15.0, 80.0),
    "soap_call": (25.0, 120.0),
    "grpc_call": (10.0, 50.0),
    "call_function": (1.0, 5.0),
    "db_query_external": (10.0, 60.0),
    "db_call_procedure": (15.0, 80.0),
    "crud_create": (8.0, 30.0),
    "crud_update": (8.0, 30.0),
    "crud_read": (5.0, 20.0),
    "rag_query": (50.0, 200.0),
    "llm_call": (200.0, 1500.0),
    "ai": (200.0, 1500.0),
    "audit": (1.0, 4.0),
    "transform": (0.1, 2.0),
    "choice": (0.1, 1.0),
    "parallel": (0.1, 1.0),
    "validate_response": (0.5, 3.0),
    "publish_event": (5.0, 30.0),
    "log": (0.1, 1.0),
}


def _step_label(step: Any, idx: int) -> str:
    if not isinstance(step, dict):
        return f"step_{idx}: {step!r}"
    if len(step) == 1:
        return next(iter(step.keys()))
    return ",".join(step.keys())


def _step_duration_ms(label: str, rng: random.Random) -> float:
    """Возвращает оценочное время шага по профилю."""
    lo, hi = _LATENCY_PROFILE.get(label, (1.0, 10.0))
    return rng.uniform(lo, hi)


def _step_preview(step: Any, payload: Any, idx: int) -> str:
    """Краткий preview output после шага."""
    if not isinstance(step, dict):
        return f"output_{idx}: {step!r}"[:120]
    label = next(iter(step.keys()))
    return f"after {label}: payload_size={len(repr(payload))}"


def dry_run_route(
    route: dict, *, sample_payload: Any = None, seed: int = 0
) -> DryRunResult:
    """Выполняет route в dry-run режиме.

    Args:
        route: dict из YAML.safe_load.
        sample_payload: sample входящий payload (для labels).
        seed: deterministic seed для latency-эмуляции.

    Returns:
        DryRunResult со списком StepResult и total_ms.
    """
    rng = random.Random(seed)  # noqa: S311  # non-cryptographic use
    steps_src = route.get("steps") or route.get("processors") or []
    result = DryRunResult(route_id=route.get("route_id"))

    payload = sample_payload
    total = 0.0
    for idx, step in enumerate(steps_src):
        label = _step_label(step, idx)
        duration = _step_duration_ms(label, rng)
        # Эмулируем реальную задержку только в server-runtime — здесь
        # достаточно записать оценку.
        preview = _step_preview(step, payload, idx)
        notes: list[str] = []
        if label not in _LATENCY_PROFILE:
            notes.append("unknown step: используем дефолт 1-10мс")
        result.steps.append(
            StepResult(
                index=idx,
                label=label,
                duration_ms=round(duration, 2),
                output_preview=preview,
                notes=notes,
            )
        )
        total += duration

    result.total_ms = round(total, 2)
    return result


def waterfall_lines(result: DryRunResult, *, width: int = 40) -> list[str]:
    """Текстовый waterfall — fixed-width '█'-блоки по длительности.

    Используется CLI 'make simulate' и Streamlit preview.
    """
    if not result.steps:
        return []

    max_dur = max((s.duration_ms for s in result.steps), default=0.0)
    if max_dur <= 0:
        max_dur = 1.0

    lines = []
    for s in result.steps:
        bar_len = max(1, int((s.duration_ms / max_dur) * width))
        bar = "█" * bar_len
        lines.append(f"[{s.index:02d}] {s.label:<24} | {bar} {s.duration_ms:.2f}ms")
    return lines


def _now_ms() -> float:
    return time.monotonic() * 1000.0
