"""Wave 1.3 (Roadmap V10) — unit-тесты Pydantic→protobuf адаптера.

Покрывает:

* скалярные типы (int/str/bool/float/bytes) → корректные protobuf-типы;
* ``Optional[T]`` → ``optional`` модификатор;
* ``list[T]`` → ``repeated`` модификатор;
* nested :class:`BaseModel` → отдельная message + ссылка по имени;
* fallback на ``google.protobuf.Any`` для сложных типов + warning;
* идемпотентность: повторная регистрация той же модели не дублирует.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel

from src.core.actions.proto_adapter import (
    ProtoFile,
    PydanticToProtoConverter,
    render_proto_file,
)


class _SimpleModel(BaseModel):
    """Простая модель со скалярами."""

    id: int
    name: str
    active: bool
    score: float


class _OptionalModel(BaseModel):
    """Модель с Optional / list."""

    description: Optional[str] = None  # noqa: UP045 — намеренно тестируем typing.Optional
    tags: list[str] = []


class _NestedInner(BaseModel):
    code: int


class _NestedOuter(BaseModel):
    """Вложенная nested-модель."""

    inner: _NestedInner
    items: list[_NestedInner] = []


class _UnionModel(BaseModel):
    """Сложный union → должен fallback в Any."""

    value: Union[int, str]


class TestScalars:
    def test_basic_scalars(self):
        conv = PydanticToProtoConverter()
        name = conv.convert_model(_SimpleModel)
        assert name == "_SimpleModel"

        msg = next(m for m in conv.messages if m.name == "_SimpleModel")
        types = {f.name: f.type_name for f in msg.fields}
        assert types == {
            "id": "int64",
            "name": "string",
            "active": "bool",
            "score": "double",
        }
        assert not conv.needs_any_import


class TestOptionalAndList:
    def test_optional_and_list(self):
        conv = PydanticToProtoConverter()
        conv.convert_model(_OptionalModel)
        msg = next(m for m in conv.messages if m.name == "_OptionalModel")

        desc = next(f for f in msg.fields if f.name == "description")
        assert desc.type_name == "string"
        assert desc.optional is True
        assert desc.repeated is False

        tags = next(f for f in msg.fields if f.name == "tags")
        assert tags.type_name == "string"
        assert tags.repeated is True
        assert tags.optional is False


class TestNested:
    def test_nested_models_create_separate_messages(self):
        conv = PydanticToProtoConverter()
        conv.convert_model(_NestedOuter)
        names = {m.name for m in conv.messages}
        assert "_NestedOuter" in names
        assert "_NestedInner" in names

        outer = next(m for m in conv.messages if m.name == "_NestedOuter")
        inner_field = next(f for f in outer.fields if f.name == "inner")
        assert inner_field.type_name == "_NestedInner"

        items_field = next(f for f in outer.fields if f.name == "items")
        assert items_field.repeated is True
        assert items_field.type_name == "_NestedInner"

    def test_idempotent(self):
        conv = PydanticToProtoConverter()
        conv.convert_model(_NestedOuter)
        before = len(conv.messages)
        conv.convert_model(_NestedOuter)
        assert len(conv.messages) == before


class TestUnionFallback:
    def test_union_falls_back_to_any(self):
        conv = PydanticToProtoConverter()
        conv.convert_model(_UnionModel)
        msg = next(m for m in conv.messages if m.name == "_UnionModel")
        value_field = next(f for f in msg.fields if f.name == "value")
        assert value_field.type_name == "google.protobuf.Any"
        assert conv.needs_any_import is True
        assert any("complex Union" in w for w in conv.warnings)


class TestRenderProtoFile:
    def test_render_minimal(self):
        from src.core.actions.proto_adapter import (
            ProtoMessage,
            ProtoService,
            ProtoServiceRpc,
        )

        proto = ProtoFile(
            package="orders.auto",
            messages=[
                ProtoMessage(
                    name="Empty",
                    fields=[],
                    comment="empty",
                )
            ],
            services=[
                ProtoService(
                    name="OrdersAutoService",
                    rpcs=[
                        ProtoServiceRpc(
                            name="List",
                            request_message="Empty",
                            response_message="Empty",
                        )
                    ],
                )
            ],
        )
        text = render_proto_file(proto)
        assert 'syntax = "proto3";' in text
        assert "package orders.auto;" in text
        assert "message Empty {" in text
        assert "service OrdersAutoService {" in text
        assert "rpc List(Empty) returns (Empty);" in text
