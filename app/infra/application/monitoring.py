from fastapi import FastAPI


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

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_group_untemplated=True,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app)
