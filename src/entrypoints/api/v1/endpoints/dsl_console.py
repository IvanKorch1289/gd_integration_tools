"""DSL Console — inline pipeline execution для отладки.

Позволяет отправить YAML-определение pipeline + payload
и получить результат с трейсом процессоров.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

__all__ = ("router",)

router = APIRouter(tags=["DSL Console"])


class InlineDSLRequest(BaseModel):
    """Запрос на выполнение inline DSL pipeline."""
    route_yaml: str = Field(
        ...,
        description="YAML-определение маршрута (route_id, processors)",
        examples=[
            'route_id: test\nprocessors:\n  - type: LogProcessor\n    level: info'
        ],
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Payload для Exchange body",
    )
    headers: dict[str, Any] = Field(
        default_factory=dict,
        description="Headers для Exchange",
    )


class InlineDSLResponse(BaseModel):
    """Результат выполнения inline DSL pipeline."""
    status: str
    result: Any = None
    error: str | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/dsl/execute-inline",
    response_model=InlineDSLResponse,
    summary="Выполнить inline DSL pipeline",
    description=(
        "Принимает YAML-определение pipeline + payload. "
        "Выполняет без регистрации. Возвращает результат и trace."
    ),
)
async def execute_inline_dsl(body: InlineDSLRequest) -> InlineDSLResponse:
    """Выполняет DSL pipeline из YAML для отладки."""
    import io
    from pathlib import Path

    try:
        import yaml

        if len(body.route_yaml) > 65536:
            return InlineDSLResponse(status="error", error="YAML too large (max 64KB)")

        route_def = yaml.safe_load(body.route_yaml)
        if not isinstance(route_def, dict) or "route_id" not in route_def:
            return InlineDSLResponse(
                status="error",
                error="Invalid YAML: missing 'route_id'",
            )

        import re
        route_id = route_def["route_id"]
        if not re.match(r"^[a-zA-Z0-9_.\-]+$", route_id):
            return InlineDSLResponse(
                status="error",
                error="Invalid route_id: only alphanumeric, dots, hyphens, underscores",
            )

        from app.dsl.hot_reload import load_yaml_route
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".dsl.yaml", delete=True, encoding="utf-8"
        ) as tmp:
            tmp.write(body.route_yaml)
            tmp.flush()
            pipeline = load_yaml_route(Path(tmp.name))

        from app.dsl.engine.execution_engine import ExecutionEngine

        engine = ExecutionEngine()
        exchange = await engine.execute(
            pipeline,
            body=body.payload,
            headers=body.headers,
        )

        result = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )
        trace = exchange.get_property("_trace", [])

        return InlineDSLResponse(
            status=exchange.status.value,
            result=result,
            error=exchange.error,
            trace=trace,
        )

    except Exception as exc:
        return InlineDSLResponse(status="error", error=str(exc))
