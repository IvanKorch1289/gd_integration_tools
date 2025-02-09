from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


__all__ = ("setup_tracing",)


async def setup_tracing(app: FastAPI):
    # Инициализация трассировки
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint="http://otel-collector:4317")
        )
    )
    trace.set_tracer_provider(tracer_provider)

    # Инструментация FastAPI
    FastAPIInstrumentor.instrument_app(app)
