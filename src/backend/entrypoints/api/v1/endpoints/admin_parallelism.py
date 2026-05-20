"""Admin endpoint для статического parallelism-анализа маршрута (S13 K5 W3 / K2 W3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.backend.core.auth.admin_roles import AdminRole, require_admin

__all__ = ("router",)

router = APIRouter(prefix="/admin/routes", tags=["Admin / DSL Parallelism"])


@router.get(
    "/{name}/parallelism-report",
    dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY)))],
)
async def parallelism_report(name: str) -> dict[str, Any]:
    """Возвращает :class:`ParallelismReport` для указанного маршрута."""
    from src.backend.dsl.analysis.parallelism_analyzer import ParallelismAnalyzer

    try:
        from src.backend.dsl.route_loader.registry import route_registry
    except ImportError:
        route_registry = None  # type: ignore[assignment]

    steps: list[dict[str, Any]] = []
    if route_registry is not None:
        try:
            route = route_registry.get(name)
            if route is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"route '{name}' not found",
                )
            steps = getattr(route, "steps", []) or []
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            steps = []

    report = ParallelismAnalyzer().analyze(steps)
    return {
        "route_id": name,
        "total_steps": report.total_steps,
        "parallel_groups": report.parallel_groups,
        "critical_path": report.critical_path,
        "estimated_speedup": report.estimated_speedup,
        "suggested_optimizations": [
            {
                "rule": h.rule,
                "severity": h.severity,
                "message": h.message,
                "affected_steps": list(h.affected_steps),
            }
            for h in report.suggested_optimizations
        ],
        "dependencies": [
            {"from": d.from_step, "to": d.to_step, "via": d.via}
            for d in report.dependencies
        ],
    }
