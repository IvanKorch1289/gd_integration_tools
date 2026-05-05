# ruff: noqa: S101, S108
"""Тесты `src.dsl.blueprints` (R2.5): шаблоны интеграционных pipeline'ов."""

from __future__ import annotations

from pydantic import BaseModel

from src.dsl.blueprints import (
    api_normalize_persist_webhook,
    cdc_enrich_publish,
    file_watch_parse_validate_action,
    request_response_with_compensation,
)
from src.dsl.engine.pipeline import Pipeline


class _Sample(BaseModel):
    id: int


class TestApiNormalizePersistWebhook:
    def test_builds_pipeline(self) -> None:
        p = api_normalize_persist_webhook(
            route_id="api.demo",
            source_url="https://example.com/data",
            persist_action="orders.create",
            webhook_url="https://hooks.example.com/notify",
            schema=_Sample,
        )
        assert isinstance(p, Pipeline)
        assert p.route_id == "api.demo"
        # 4 processors: http_call + normalize + dispatch_action + http_call.
        assert len(p.processors) == 4

    def test_without_schema_skips_normalize(self) -> None:
        p = api_normalize_persist_webhook(
            route_id="r",
            source_url="https://example.com/data",
            persist_action="orders.create",
            webhook_url="https://hooks.example.com/notify",
        )
        # 3 processors: http_call + dispatch_action + http_call.
        assert len(p.processors) == 3


class TestCdcEnrichPublish:
    def test_builds_pipeline(self) -> None:
        p = cdc_enrich_publish(
            route_id="cdc.orders",
            cdc_source="cdc:postgres/orders",
            enrichment_url="https://enrich.example.com/data",
            publish_action="messaging.publish_event",
        )
        assert isinstance(p, Pipeline)
        assert p.route_id == "cdc.orders"
        # http_call (enrich) + dispatch_action (publish).
        assert len(p.processors) == 2


class TestFileWatchParseValidateAction:
    def test_with_schema(self) -> None:
        p = file_watch_parse_validate_action(
            route_id="fw.demo",
            watch_path="/tmp/inbox",
            file_glob="*.json",
            schema=_Sample,
            action="documents.process",
        )
        assert isinstance(p, Pipeline)
        assert p.route_id == "fw.demo"
        # normalize + validate + dispatch_action.
        assert len(p.processors) == 3

    def test_without_schema(self) -> None:
        p = file_watch_parse_validate_action(
            route_id="fw.basic",
            watch_path="/tmp/inbox",
            file_glob="*.csv",
            action="data.ingest",
        )
        # Только dispatch_action.
        assert len(p.processors) == 1


class TestRequestResponseWithCompensation:
    def test_builds_saga_pipeline(self) -> None:
        p = request_response_with_compensation(
            route_id="payment.charge",
            request_url="https://gateway.example.com/charge",
            compensate_url="https://gateway.example.com/refund",
        )
        assert isinstance(p, Pipeline)
        assert p.route_id == "payment.charge"
        # Один saga-processor.
        assert len(p.processors) == 1
        proc = p.processors[0]
        assert "saga" in proc.name

    def test_with_extra_processors(self) -> None:
        from src.dsl.engine.context import ExecutionContext
        from src.dsl.engine.exchange import Exchange
        from src.dsl.engine.processors.base import BaseProcessor

        class _Noop(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="noop")

            async def process(
                self, exchange: Exchange, context: ExecutionContext
            ) -> None:  # pragma: no cover
                return None

        p = request_response_with_compensation(
            route_id="r",
            request_url="https://x.example.com",
            compensate_url="https://y.example.com",
            extra_processors=[_Noop(), _Noop()],
        )
        # saga + 2 extra.
        assert len(p.processors) == 3
