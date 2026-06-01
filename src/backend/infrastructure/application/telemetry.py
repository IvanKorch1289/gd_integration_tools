from fastapi import FastAPI

__all__ = ("setup_tracing",)


def setup_tracing(app: FastAPI):
    """
    Настраивает трассировку для FastAPI-приложения с использованием OpenTelemetry.

    Args:
        app (FastAPI): Экземпляр FastAPI-приложения, для которого настраивается трассировка.

    Описание:
        Функция инициализирует трассировку с использованием OpenTelemetry и настраивает экспорт
        данных трассировки в OTLP-совместимый сборщик (например, Jaeger или Grafana Tempo).
        Также выполняется инструментация FastAPI для автоматического сбора данных о запросах.
    """
    # Инициализация трассировки
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from src.backend.core.config.settings import settings

    resource = Resource.create(
        {
            "service.name": settings.app.title,
            "service.version": settings.app.version,
            "deployment.environment": settings.app.environment,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    span_exporter = OTLPSpanExporter(
        endpoint=settings.app.opentelemetry_endpoint, insecure=True
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))

    trace.set_tracer_provider(tracer_provider)
    FastAPIInstrumentor.instrument_app(app)
