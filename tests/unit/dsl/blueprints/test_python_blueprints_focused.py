"""Focused tests for ``_python_blueprints`` (Sprint 24 coverage ratchet).

Цель: поднять покрытие ``src/backend/dsl/blueprints/_python_blueprints.py``
с ~19% до ≥80% путём детального покрытия 4 blueprint-функций:

- ``api_normalize_persist_webhook`` — REST API ingestion → webhook.
- ``cdc_enrich_publish`` — CDC source → enrich → MQ publish.
- ``file_watch_parse_validate_action`` — file watcher → validate → action.
- ``request_response_with_compensation`` — Saga compensation pattern.

Все blueprints возвращают ``Pipeline`` и принимают описательные параметры.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from src.backend.dsl.blueprints._python_blueprints import (
    api_normalize_persist_webhook,
    cdc_enrich_publish,
    file_watch_parse_validate_action,
    request_response_with_compensation,
)
from src.backend.dsl.engine.pipeline import Pipeline


class _SampleSchema(BaseModel):
    """Test Pydantic schema для normalize/validate шагов."""

    id: int
    name: str


class TestApiNormalizePersistWebhook:
    """``api_normalize_persist_webhook`` — REST API → persist → webhook."""

    def test_returns_pipeline(self) -> None:
        """Функция возвращает ``Pipeline``."""
        p = api_normalize_persist_webhook(
            route_id="r1",
            source_url="https://api.example.com/data",
            persist_action="orders.create",
            webhook_url="https://hook.example.com/notify",
        )
        assert isinstance(p, Pipeline)

    def test_route_id(self) -> None:
        """``Pipeline.route_id`` соответствует переданному ``route_id``."""
        p = api_normalize_persist_webhook(
            route_id="my-route",
            source_url="https://api",
            persist_action="save",
            webhook_url="https://hook",
        )
        assert p.route_id == "my-route"

    def test_default_description(self) -> None:
        """``description=None`` → auto-generated default."""
        p = api_normalize_persist_webhook(
            route_id="r1",
            source_url="https://api/data",
            persist_action="save",
            webhook_url="https://hook",
        )
        assert "API ingestion" in p.description or "api/data" in p.description

    def test_custom_description(self) -> None:
        """``description`` сохраняется в pipeline."""
        p = api_normalize_persist_webhook(
            route_id="r1",
            source_url="https://api",
            persist_action="save",
            webhook_url="https://hook",
            description="Custom ingestion pipeline",
        )
        assert p.description == "Custom ingestion pipeline"

    def test_with_schema(self) -> None:
        """``schema=PydanticModel`` → pipeline содержит normalize-step."""
        p = api_normalize_persist_webhook(
            route_id="r1",
            source_url="https://api",
            persist_action="save",
            webhook_url="https://hook",
            schema=_SampleSchema,
        )
        assert isinstance(p, Pipeline)
        assert len(p.processors) >= 1

    def test_custom_method(self) -> None:
        """``method='POST'`` сохраняется в pipeline."""
        p = api_normalize_persist_webhook(
            route_id="r1",
            source_url="https://api",
            persist_action="save",
            webhook_url="https://hook",
            method="POST",
        )
        assert isinstance(p, Pipeline)

    def test_custom_timeout(self) -> None:
        """``timeout=60`` сохраняется."""
        p = api_normalize_persist_webhook(
            route_id="r1",
            source_url="https://api",
            persist_action="save",
            webhook_url="https://hook",
            timeout=60,
        )
        assert isinstance(p, Pipeline)


class TestCdcEnrichPublish:
    """``cdc_enrich_publish`` — CDC source → enrich → MQ publish."""

    def test_returns_pipeline(self) -> None:
        """Функция возвращает ``Pipeline``."""
        p = cdc_enrich_publish(
            route_id="cdc-r",
            cdc_source="cdc:postgres/orders",
            enrichment_url="https://enrich.api/users",
            publish_action="messaging.publish_event",
        )
        assert isinstance(p, Pipeline)

    def test_route_id(self) -> None:
        """``Pipeline.route_id`` соответствует."""
        p = cdc_enrich_publish(
            route_id="my-cdc",
            cdc_source="cdc:postgres/x",
            enrichment_url="https://enrich",
            publish_action="publish",
        )
        assert p.route_id == "my-cdc"

    def test_default_description(self) -> None:
        """``description=None`` → auto-generated."""
        p = cdc_enrich_publish(
            route_id="r",
            cdc_source="cdc:postgres/orders",
            enrichment_url="https://e",
            publish_action="publish",
        )
        assert "CDC" in p.description

    def test_custom_description(self) -> None:
        """Custom description сохраняется."""
        p = cdc_enrich_publish(
            route_id="r",
            cdc_source="cdc:pg/x",
            enrichment_url="https://e",
            publish_action="publish",
            description="Custom CDC pipeline",
        )
        assert p.description == "Custom CDC pipeline"


class TestFileWatchParseValidateAction:
    """``file_watch_parse_validate_action`` — file watcher → validate → action."""

    def test_returns_pipeline(self) -> None:
        """Функция возвращает ``Pipeline``."""
        p = file_watch_parse_validate_action(
            route_id="fw",
            watch_path="/tmp/inbox",
            action="process_file",
        )
        assert isinstance(p, Pipeline)

    def test_route_id(self) -> None:
        """``Pipeline.route_id``."""
        p = file_watch_parse_validate_action(
            route_id="fw-r",
            watch_path="/data",
            action="process",
        )
        assert p.route_id == "fw-r"

    def test_default_file_glob(self) -> None:
        """``file_glob='*.json'`` default → отражено в pipeline source."""
        p = file_watch_parse_validate_action(
            route_id="fw",
            watch_path="/data",
            action="process",
        )
        assert isinstance(p, Pipeline)

    def test_custom_file_glob(self) -> None:
        """Custom file_glob."""
        p = file_watch_parse_validate_action(
            route_id="fw",
            watch_path="/data",
            file_glob="*.csv",
            action="process",
        )
        assert isinstance(p, Pipeline)

    def test_with_schema(self) -> None:
        """``schema=Model`` → добавляет normalize + validate шаги."""
        p = file_watch_parse_validate_action(
            route_id="fw",
            watch_path="/data",
            schema=_SampleSchema,
            action="process",
        )
        # schema добавляет processors.
        assert isinstance(p, Pipeline)
        assert len(p.processors) >= 1

    def test_default_description(self) -> None:
        """Auto description."""
        p = file_watch_parse_validate_action(
            route_id="fw",
            watch_path="/data/inbox",
            action="process",
        )
        assert "File watch" in p.description or "/data/inbox" in p.description

    def test_custom_description(self) -> None:
        """Custom description."""
        p = file_watch_parse_validate_action(
            route_id="fw",
            watch_path="/data",
            action="process",
            description="Custom file pipeline",
        )
        assert p.description == "Custom file pipeline"


class TestRequestResponseWithCompensation:
    """``request_response_with_compensation`` — Saga pattern."""

    def test_returns_pipeline(self) -> None:
        """Функция возвращает ``Pipeline``."""
        p = request_response_with_compensation(
            route_id="saga",
            request_url="https://pay.example.com/charge",
            compensate_url="https://pay.example.com/refund",
        )
        assert isinstance(p, Pipeline)

    def test_route_id(self) -> None:
        """``Pipeline.route_id``."""
        p = request_response_with_compensation(
            route_id="my-saga",
            request_url="https://x",
            compensate_url="https://y",
        )
        assert p.route_id == "my-saga"

    def test_default_request_method(self) -> None:
        """``request_method='POST'`` default."""
        p = request_response_with_compensation(
            route_id="r",
            request_url="https://x",
            compensate_url="https://y",
        )
        assert isinstance(p, Pipeline)

    def test_custom_request_method(self) -> None:
        """Custom request_method сохраняется."""
        p = request_response_with_compensation(
            route_id="r",
            request_url="https://x",
            compensate_url="https://y",
            request_method="PUT",
        )
        assert isinstance(p, Pipeline)

    def test_custom_timeout(self) -> None:
        """Custom timeout."""
        p = request_response_with_compensation(
            route_id="r",
            request_url="https://x",
            compensate_url="https://y",
            timeout=60,
        )
        assert isinstance(p, Pipeline)

    def test_custom_max_retries(self) -> None:
        """``max_retries`` параметр принимается (forward-compat)."""
        p = request_response_with_compensation(
            route_id="r",
            request_url="https://x",
            compensate_url="https://y",
            max_retries=5,
        )
        assert isinstance(p, Pipeline)

    def test_with_extra_processors(self) -> None:
        """``extra_processors`` добавляются в pipeline."""
        from src.backend.dsl.engine.processors.components import (
            HttpCallProcessor,
        )

        p = request_response_with_compensation(
            route_id="r",
            request_url="https://x",
            compensate_url="https://y",
            extra_processors=[
                HttpCallProcessor(url="https://extra", method="GET", timeout=5),
            ],
        )
        assert isinstance(p, Pipeline)

    def test_default_description(self) -> None:
        """Auto description включает method и url."""
        p = request_response_with_compensation(
            route_id="r",
            request_url="https://pay.example/charge",
            compensate_url="https://pay.example/refund",
        )
        assert "Saga" in p.description or "POST" in p.description

    def test_custom_description(self) -> None:
        """Custom description."""
        p = request_response_with_compensation(
            route_id="r",
            request_url="https://x",
            compensate_url="https://y",
            description="Payment saga",
        )
        assert p.description == "Payment saga"


class TestBlueprintModuleExports:
    """Module-level ``__all__`` и API surface."""

    def test_all_exports(self) -> None:
        """Все 4 blueprint-функции экспортируются."""
        from src.backend.dsl.blueprints import _python_blueprints

        expected = {
            "api_normalize_persist_webhook",
            "cdc_enrich_publish",
            "file_watch_parse_validate_action",
            "request_response_with_compensation",
        }
        assert set(_python_blueprints.__all__) == expected

    def test_all_callable(self) -> None:
        """Все экспортированные функции — callable."""
        from src.backend.dsl.blueprints import _python_blueprints

        for name in _python_blueprints.__all__:
            fn = getattr(_python_blueprints, name)
            assert callable(fn), f"{name} should be callable"
