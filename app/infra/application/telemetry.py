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
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from app.config.settings import settings

    # Создание провайдера трассировки
    tracer_provider = TracerProvider()

    # Настройка экспорта данных трассировки в OTLP-совместимый сборщик
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.app.opentelemetry_endpoint)
        )
    )

    # Установка провайдера трассировки
    trace.set_tracer_provider(tracer_provider)

    # Инструментация FastAPI для автоматического сбора данных о запросах
    FastAPIInstrumentor.instrument_app(app)
