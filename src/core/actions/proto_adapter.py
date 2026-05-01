"""Адаптер Pydantic → protobuf3 schema (Wave 1.3, Roadmap V10).

Используется ``tools/codegen_proto.py`` для генерации ``.proto`` файлов
из :class:`ActionMetadata`. Поддерживает минимально достаточный
набор типов:

* ``int`` → ``int64``;
* ``float`` → ``double``;
* ``bool`` → ``bool``;
* ``str``  → ``string``;
* ``bytes`` → ``bytes``;
* ``list[T]`` → ``repeated T``;
* ``Optional[T]`` → ``T`` с пометкой ``optional`` (proto3 syntax);
* nested :class:`pydantic.BaseModel` → отдельная message;
* всё остальное (Union сложного вида, Generic, custom) →
  ``google.protobuf.Any`` + предупреждение.

Адаптер не зависит от ``grpc-tools`` — только Pydantic + stdlib.
``tools/codegen_proto.py`` уже использует ``grpc_tools.protoc`` для
компиляции сгенерированных файлов.

Layer policy: модуль живёт в ``src/core/actions/`` и не импортирует
``entrypoints``/``infrastructure``. Pydantic — допустимая pip-зависимость.
"""

from __future__ import annotations

import logging
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

__all__ = (
    "ProtoField",
    "ProtoMessage",
    "ProtoFile",
    "PydanticToProtoConverter",
    "render_proto_file",
)

logger = logging.getLogger(__name__)


# Маппинг базовых Python-типов в protobuf3 scalar-типы.
_SCALAR_MAP: dict[type, str] = {
    int: "int64",
    float: "double",
    bool: "bool",
    str: "string",
    bytes: "bytes",
}


@dataclass(slots=True)
class ProtoField:
    """Описание одного поля protobuf-сообщения.

    Attributes:
        name: Имя поля (snake_case).
        type_name: Имя protobuf-типа (``int64``, ``string``, ``MyMessage``,
            ``google.protobuf.Any``).
        number: Порядковый номер (1-based).
        repeated: Признак ``repeated`` (для ``list[T]``).
        optional: Признак ``optional`` (для ``Optional[T]`` в proto3).
        comment: Комментарий, попадает в ``.proto`` как ``// comment``.
    """

    name: str
    type_name: str
    number: int
    repeated: bool = False
    optional: bool = False
    comment: str | None = None


@dataclass(slots=True)
class ProtoMessage:
    """Описание одной protobuf-message.

    Attributes:
        name: Имя сообщения (CamelCase).
        fields: Список :class:`ProtoField`.
        comment: Описание сообщения (попадает в ``.proto``).
    """

    name: str
    fields: list[ProtoField] = field(default_factory=list)
    comment: str | None = None


@dataclass(slots=True)
class ProtoServiceRpc:
    """Описание одной RPC-операции сервиса.

    Attributes:
        name: Имя RPC-метода (CamelCase, например ``ListOrders``).
        request_message: Имя input-message.
        response_message: Имя output-message.
        comment: Описание метода.
    """

    name: str
    request_message: str
    response_message: str
    comment: str | None = None


@dataclass(slots=True)
class ProtoService:
    """Описание protobuf-сервиса.

    Attributes:
        name: Имя сервиса (например ``OrdersService``).
        rpcs: Список RPC-методов.
        comment: Описание сервиса.
    """

    name: str
    rpcs: list[ProtoServiceRpc] = field(default_factory=list)
    comment: str | None = None


@dataclass(slots=True)
class ProtoFile:
    """Описание одного ``.proto`` файла.

    Attributes:
        package: protobuf-package (``orders.auto``).
        messages: Все message-определения.
        services: Все service-определения.
        imports: Дополнительные ``import "..."`` (для ``Any`` — google/protobuf/any.proto).
        warnings: Предупреждения, накопленные при конвертации
            (например, fallback на ``google.protobuf.Any``).
    """

    package: str
    messages: list[ProtoMessage] = field(default_factory=list)
    services: list[ProtoService] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


class PydanticToProtoConverter:
    """Конвертер :class:`BaseModel` → :class:`ProtoMessage`.

    Поддерживает рекурсию (nested models) и идемпотентен:
    для повторно встреченной модели возвращается уже зарегистрированное
    имя без повторной генерации.
    """

    def __init__(self) -> None:
        self._messages: dict[str, ProtoMessage] = {}
        self._warnings: list[str] = []
        self._needs_any: bool = False

    @property
    def messages(self) -> tuple[ProtoMessage, ...]:
        """Все сгенерированные message в порядке регистрации."""
        return tuple(self._messages.values())

    @property
    def warnings(self) -> tuple[str, ...]:
        """Накопленные warnings (fallback на ``Any`` и т.п.)."""
        return tuple(self._warnings)

    @property
    def needs_any_import(self) -> bool:
        """Есть ли поля, использующие ``google.protobuf.Any``."""
        return self._needs_any

    def convert_model(self, model: type[BaseModel]) -> str:
        """Зарегистрировать :class:`BaseModel` и вернуть имя protobuf-message.

        Args:
            model: Pydantic-модель.

        Returns:
            Имя сгенерированной message (CamelCase, совпадает с именем класса).
        """
        message_name = model.__name__
        if message_name in self._messages:
            return message_name

        message = ProtoMessage(
            name=message_name,
            comment=(model.__doc__ or "").strip().splitlines()[0]
            if model.__doc__
            else None,
        )
        # Сохраняем заранее, чтобы рекурсивные ссылки работали.
        self._messages[message_name] = message

        for index, (field_name, info) in enumerate(model.model_fields.items(), start=1):
            annotation = info.annotation
            field_obj = self._convert_annotation(field_name, annotation, index)
            message.fields.append(field_obj)
        return message_name

    # ------------------------------------------------------------------ #
    # Internal: annotation → ProtoField                                  #
    # ------------------------------------------------------------------ #

    def _convert_annotation(
        self, name: str, annotation: Any, number: int
    ) -> ProtoField:
        """Сконвертировать одну аннотацию поля Pydantic в :class:`ProtoField`."""
        if annotation is None:
            self._record_any(f"{name}: None type")
            return ProtoField(
                name=name, type_name="google.protobuf.Any", number=number
            )

        # Optional[T] / T | None → optional
        if _is_optional(annotation):
            inner = _strip_optional(annotation)
            field_obj = self._convert_annotation(name, inner, number)
            field_obj.optional = True
            return field_obj

        origin = get_origin(annotation)

        # list[T] → repeated
        if origin in (list, tuple, set, frozenset):
            args = get_args(annotation)
            if not args:
                self._record_any(f"{name}: untyped {origin.__name__}")
                return ProtoField(
                    name=name,
                    type_name="google.protobuf.Any",
                    number=number,
                    repeated=True,
                )
            inner_field = self._convert_annotation(name, args[0], number)
            inner_field.repeated = True
            inner_field.optional = False  # repeated сам по себе допускает 0 элементов
            return inner_field

        # Union (не Optional) — используем Any
        if origin is Union or origin is types.UnionType:
            self._record_any(f"{name}: complex Union {annotation!r}")
            return ProtoField(
                name=name,
                type_name="google.protobuf.Any",
                number=number,
            )

        # dict[K, V] → google.protobuf.Any (proto3 map тяжёл для адаптера)
        if origin in (dict,):
            self._record_any(f"{name}: dict — fallback to Any")
            return ProtoField(
                name=name, type_name="google.protobuf.Any", number=number
            )

        # Scalar
        if isinstance(annotation, type) and annotation in _SCALAR_MAP:
            return ProtoField(
                name=name, type_name=_SCALAR_MAP[annotation], number=number
            )

        # Nested BaseModel — рекурсия
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            nested_name = self.convert_model(annotation)
            return ProtoField(name=name, type_name=nested_name, number=number)

        # Enum / специальные типы → string (унифицированный сериализуемый вид)
        if isinstance(annotation, type) and _is_enum_like(annotation):
            return ProtoField(name=name, type_name="string", number=number)

        # Fallback на Any
        self._record_any(f"{name}: unsupported {annotation!r}")
        return ProtoField(
            name=name,
            type_name="google.protobuf.Any",
            number=number,
            comment=f"unsupported {annotation!r}",
        )

    def _record_any(self, reason: str) -> None:
        """Зафиксировать использование ``google.protobuf.Any`` + warning."""
        self._needs_any = True
        message = f"proto-codegen fallback to google.protobuf.Any: {reason}"
        self._warnings.append(message)
        logger.warning(message)


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _is_optional(annotation: Any) -> bool:
    """Проверить, что ``annotation`` — ``Optional[T]`` (``T | None``)."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return type(None) in get_args(annotation)
    return False


def _strip_optional(annotation: Any) -> Any:
    """Убрать ``None`` из ``Optional[T]``, вернуть ``T`` (или ``Union[...]``)."""
    args = tuple(arg for arg in get_args(annotation) if arg is not type(None))
    if len(args) == 1:
        return args[0]
    # Несколько ненулевых членов — оставляем как Union (попадёт в Any в _convert_annotation).
    return typing.Union[args]  # noqa: UP007


def _is_enum_like(tp: type) -> bool:
    """Проверить, что ``tp`` — Enum-like класс (для упрощения маппинга в string)."""
    try:
        from enum import Enum

        return issubclass(tp, Enum)
    except TypeError:
        return False


# ---------------------------------------------------------------------- #
# Renderer: ProtoFile → text                                              #
# ---------------------------------------------------------------------- #


def render_proto_file(proto: ProtoFile) -> str:
    """Сериализовать :class:`ProtoFile` в текстовое представление ``.proto``.

    Возвращает строку, готовую к записи на диск. Формат — proto3.
    """
    lines: list[str] = ['syntax = "proto3";', ""]
    lines.append(f"package {proto.package};")
    lines.append("")

    # Imports
    imports = sorted(proto.imports)
    if proto.warnings:
        # Если есть warning'и, обычно есть и Any — удостоверимся, что google/protobuf/any.proto импортирован.
        pass
    for imp in imports:
        lines.append(f'import "{imp}";')
    if imports:
        lines.append("")

    # Messages
    for message in proto.messages:
        if message.comment:
            lines.append(f"// {message.comment}")
        lines.append(f"message {message.name} {{")
        for field_obj in message.fields:
            modifiers: list[str] = []
            if field_obj.repeated:
                modifiers.append("repeated")
            elif field_obj.optional:
                modifiers.append("optional")
            modifier = (" ".join(modifiers) + " ") if modifiers else ""
            comment_suffix = f"  // {field_obj.comment}" if field_obj.comment else ""
            lines.append(
                f"  {modifier}{field_obj.type_name} {field_obj.name} = "
                f"{field_obj.number};{comment_suffix}"
            )
        lines.append("}")
        lines.append("")

    # Services
    for service in proto.services:
        if service.comment:
            lines.append(f"// {service.comment}")
        lines.append(f"service {service.name} {{")
        for rpc in service.rpcs:
            comment = f"  // {rpc.comment}\n" if rpc.comment else ""
            lines.append(
                f"{comment}  rpc {rpc.name}({rpc.request_message}) "
                f"returns ({rpc.response_message});"
            )
        lines.append("}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
