from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator
from starlette_exporter import handle_metrics


__all__ = ("setup_monitoring",)


async def setup_monitoring(app: FastAPI):
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_group_untemplated=True,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app)

    @app.get(
        "/metrics", summary="metrics", operation_id="metrics", tags=["Метрики"]
    )
    async def metrics(request: Request):
        return handle_metrics(request)
