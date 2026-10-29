"""ADR-0384 — DSL-путь CDC: builder-метод ``cdc_capture`` и ``from_cdc_capture``.

Регрессии волны 16 (кластер X5, дефект 3):

* YAML-шаг ``cdc_capture`` падал с ``Unknown or forbidden processor
  'cdc_capture'`` — метода не было в ``RouteBuilder``;
* ``from_cdc_capture`` писал ``_source_config``, который никто не читал —
  процессор в pipeline не добавлялся;
* ``CDCCaptureProcessor`` подписывался с ``callback=None`` — события
  дропались и не доходили до ``result_property``.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.processors.cdc_capture import CDCCaptureProcessor
from src.backend.dsl.yaml_loader.loaders import load_pipeline_from_yaml


@pytest.mark.unit
def test_cdc_capture_builder_method_adds_processor() -> None:
    """``.cdc_capture(...)`` — публичный метод RouteBuilder (YAML-whitelist)."""
    builder = RouteBuilder.from_("orders.changes", "cdc:orders")

    builder.cdc_capture(
        profile="pg_prod",
        tables=["orders"],
        strategy="polling",
        result_property="cdc_events",
    )
    pipeline = builder.build()

    assert len(pipeline.processors) == 1
    processor = pipeline.processors[0]
    assert isinstance(processor, CDCCaptureProcessor)
    assert processor._profile == "pg_prod"
    assert processor._tables == ["orders"]
    assert processor._strategy == "polling"
    assert processor._result_property == "cdc_events"


@pytest.mark.unit
def test_from_cdc_capture_reads_source_config() -> None:
    """``from_cdc_capture`` читает записанный ``_source_config``."""
    builder = RouteBuilder.from_cdc_capture(
        "orders.changes",
        "pg_prod",
        ["orders", "customers"],
        strategy="kafka",
        interval=15.0,
        batch_size=50,
    )

    config = builder._source_config
    assert config["profile"] == "pg_prod"
    assert config["strategy"] == "kafka"

    pipeline = builder.build()
    assert len(pipeline.processors) == 1
    processor = pipeline.processors[0]
    assert isinstance(processor, CDCCaptureProcessor)
    # Значения взяты из _source_config, а не из дефолтов.
    assert processor._profile == config["profile"]
    assert processor._strategy == config["strategy"]
    assert processor._tables == config["tables"]
    assert processor._interval == config["interval"]
    assert processor._batch_size == config["batch_size"]


@pytest.mark.unit
def test_yaml_cdc_capture_step_is_allowed() -> None:
    """YAML-шаг ``cdc_capture`` больше не отвергается whitelist'ом."""
    yaml_text = """
route_id: orders.changes
source: cdc:orders
steps:
  - cdc_capture:
      profile: pg_prod
      tables:
        - orders
      strategy: polling
      result_property: cdc_events
"""
    pipeline = load_pipeline_from_yaml(yaml_text)

    assert len(pipeline.processors) == 1
    processor = pipeline.processors[0]
    assert isinstance(processor, CDCCaptureProcessor)
    assert processor._profile == "pg_prod"
    assert processor._tables == ["orders"]
