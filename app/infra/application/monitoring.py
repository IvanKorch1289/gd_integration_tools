from fastapi import FastAPI, Request


__all__ = ("setup_monitoring",)


def setup_monitoring(app: FastAPI):
    """
    Настраивает мониторинг для FastAPI приложения с использованием Prometheus.

    Подключает инструментацию для сбора метрик, настраивает эндпоинт /metrics
    для предоставления данных в формате Prometheus и исключает сам эндпоинт
    /metrics из сбора метрик.

    Параметры:
    - app: FastAPI - экземпляр приложения FastAPI, к которому применяется мониторинг
    """
    from prometheus_fastapi_instrumentator import Instrumentator
    from starlette_exporter import handle_metrics

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
        """
        Эндпоинт для предоставления метрик приложения в формате Prometheus.

        Возвращает:
        - Текстовые данные в формате Prometheus со всеми собранными метриками

        Теги:
        - Метрики: Группа эндпоинтов для работы с метриками мониторинга

        Параметры:
        - request: Request - объект запроса Starlette
        """
        return handle_metrics(request)
