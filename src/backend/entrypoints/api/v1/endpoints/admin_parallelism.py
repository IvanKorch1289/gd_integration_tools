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
    summary="Parallelism analysis для DSL маршрута",
    description=(
        "Возвращает ParallelismReport для указанного route: "
        "total_steps, parallel_groups, critical_path, estimated_speedup, "
        "suggested_optimizations, dependencies. Используется для "
        "выявления bottleneck'ов и возможностей параллелизации в DSL "
        "маршрутах. Доступ: Operator или Read-Only admin role."
    ),
    tags=["Admin / DSL Parallelism"],
    responses={
        200: {"description": "ParallelismReport с метриками и рекомендациями."},
        401: {"description": "Missing/invalid admin credentials."},
        403: {"description": "User lacks Operator/Read-Only role."},
        404: {"description": "Route не найден."},
    },
)
async def parallelism_report(name: str) -> dict[str, Any]:
    """Возвращает :class:`ParallelismReport` для указанного маршрута."""
    # S260 re-audit (round 4): previous import was BROKEN (line 37:
    # `from ...extensions import # NOTE: ...` — syntax error: import
    # statement with comment-only, no actual names). Sprint D.3-D.4
    # refactor (1bb76b0a) added extensions facade but missed this
    # site. Using canonical full path.
    from src.backend.core.api.extensions import ParallelismAnalyzer

    try:
        # D-AUDIT-11701 fix (cycle 117): canonical path
        # src.backend.dsl.registry (НЕ src.backend.dsl.route_loader.registry
        # — модуль НЕ существует, type: ignore suppress'ил lint но
        # runtime всегда падал в ImportError → route_registry=None →
        # steps=[]. Реальный route_registry singleton: canonical
        # path src.backend.dsl.registry (re-export from
        # src.backend.dsl.commands.registry).
        from src.backend.core.api.extensions import route_registry
    except ImportError:
        route_registry = None

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
        except Exception as _:
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
