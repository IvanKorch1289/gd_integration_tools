"""PR markdown генератор для route-optimization (Sprint 11 K4 W7)."""

from __future__ import annotations

from typing import Any

__all__ = ("PRGenerator",)


class PRGenerator:
    """Собирает markdown-отчёт + DSL patch suggestions."""

    @staticmethod
    def render(route_name: str, metrics: list[Any], recommendations: list[Any]) -> str:
        """Сформировать markdown для PR."""
        lines: list[str] = []
        lines.append(f"# AI Route Optimization: `{route_name}`")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append(f"* Шагов проанализировано: **{len(metrics)}**")
        lines.append(f"* Рекомендаций: **{len(recommendations)}**")
        total_gain = sum(getattr(r, "estimated_gain_ms", 0.0) for r in recommendations)
        lines.append(f"* Потенциальная экономия: ~**{total_gain:.0f}ms** p95")
        lines.append("")
        if metrics:
            lines.append("## Метрики per step (top-5 по p95)")
            lines.append("")
            lines.append(
                "| Шаг | Requests | Errors | p50 ms | p95 ms | p99 ms | retries |"
            )
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for m in metrics[:5]:
                lines.append(
                    f"| `{m.step_name}` | {m.request_count} | {m.error_count} | "
                    f"{m.p50_latency_ms:.0f} | {m.p95_latency_ms:.0f} | "
                    f"{m.p99_latency_ms:.0f} | {m.avg_retry_count:.1f} |"
                )
            lines.append("")
        if recommendations:
            lines.append("## Рекомендации")
            lines.append("")
            for r in recommendations:
                lines.append(
                    f"### `{r.step_name}` — {r.kind} (priority **{r.priority}**)"
                )
                lines.append("")
                lines.append(r.rationale)
                lines.append("")
                if r.estimated_gain_ms:
                    lines.append(
                        f"_Ожидаемая экономия: ~{r.estimated_gain_ms:.0f}ms p95._"
                    )
                    lines.append("")
        return "\n".join(lines).rstrip() + "\n"
