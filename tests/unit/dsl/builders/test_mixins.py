"""Unit-тесты для builder mixins (partition, jinja_template, data_store_set,
batch_insert, content_filter, content_transform, unique, flatten).

Покрывают fluent-интерфейс, тип добавленного процессора и to_spec().
"""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.processors import FilterProcessor, TransformProcessor
from src.backend.dsl.engine.processors.batch import BatchInsertProcessor
from src.backend.dsl.engine.processors.data_store import DataStoreSetProcessor
from src.backend.dsl.engine.processors.eip.collection import (
    FlattenProcessor,
    PartitionProcessor,
    UniqueProcessor,
)
from src.backend.dsl.engine.processors.template_engine import RenderTemplateProcessor


class TestPartition:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.partition", source="internal:test")
        result = builder.partition(field="status")
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_partition_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.partition", source="internal:test")
            .partition(field="status")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, PartitionProcessor)

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.partition", source="internal:test")
            .partition(field="status")
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {"partition": {"field": "status", "predicate": None}}


class TestJinjaTemplate:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.jinja", source="internal:test")
        result = builder.jinja_template(template_string="Hello {{name}}")
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_render_template_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.jinja", source="internal:test")
            .jinja_template(template_string="Hello {{name}}")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, RenderTemplateProcessor)

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.jinja", source="internal:test")
            .jinja_template(template_string="Hello {{name}}")
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {
            "render_template": {
                "template_string": "Hello {{name}}",
                "context_from": "body",
                "result_property": "rendered",
            }
        }


class TestDataStoreSet:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.ds", source="internal:test")
        result = builder.data_store_set(key="session_id", value="abc123")
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_data_store_set_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.ds", source="internal:test")
            .data_store_set(key="session_id", value="abc123")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, DataStoreSetProcessor)

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.ds", source="internal:test")
            .data_store_set(key="session_id", value="abc123")
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {"data_store_set": {"key": "session_id", "value": "abc123"}}


class TestBatchInsert:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.batch", source="internal:test")
        result = builder.batch_insert(table="users")
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_batch_insert_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.batch", source="internal:test")
            .batch_insert(table="users")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, BatchInsertProcessor)

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.batch", source="internal:test")
            .batch_insert(table="users")
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {
            "batch_insert": {"table": "users", "items": None, "profile": "default"}
        }


class TestContentFilter:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.filter", source="internal:test")
        result = builder.content_filter(predicate=lambda e: True)
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_filter_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.filter", source="internal:test")
            .content_filter(predicate=lambda e: True)
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, FilterProcessor)

    def test_predicate_set(self) -> None:
        pred = lambda e: True  # noqa: E731
        pipeline = (
            RouteBuilder.from_("test.filter", source="internal:test")
            .content_filter(predicate=pred)
            .build()
        )
        proc = pipeline.processors[0]
        assert proc._predicate is pred


class TestContentTransform:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.transform", source="internal:test")
        result = builder.content_transform(expression="orders[0]")
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_transform_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.transform", source="internal:test")
            .content_transform(expression="orders[0]")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, TransformProcessor)

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.transform", source="internal:test")
            .content_transform(expression="orders[0]")
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {"transform": {"expression": "orders[0]"}}


class TestUnique:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.unique", source="internal:test")
        result = builder.unique(field="id")
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_unique_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.unique", source="internal:test")
            .unique(field="id")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, UniqueProcessor)

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.unique", source="internal:test")
            .unique(field="id")
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {"unique": {"field": "id", "key_fn": None}}


class TestFlatten:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.flatten", source="internal:test")
        result = builder.flatten(depth=2)
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_flatten_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.flatten", source="internal:test")
            .flatten(depth=2)
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, FlattenProcessor)

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.flatten", source="internal:test")
            .flatten(depth=2)
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {"flatten": {"depth": 2}}
