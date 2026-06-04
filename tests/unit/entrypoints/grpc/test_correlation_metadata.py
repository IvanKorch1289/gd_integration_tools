# ruff: noqa: S101
"""Тесты gRPC correlation_id propagation (S17 K3 W3 D12).

Покрывают helper ``_extract_correlation_id_from_grpc_context``:

* отсутствие context → "";
* отсутствие invocation_metadata → "";
* пустая metadata → "";
* metadata с ``x-correlation-id`` → значение;
* метаданные как tuple-list (legacy grpc.aio); как objects с .key/.value;
* регистро-нечувствительный matching key (``X-Correlation-ID`` тоже).

Не запускаем реальный grpc-сервер: hand-rolled mock ``invocation_metadata()``
полностью покрывает контракт gRPC servicer'а.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.entrypoints.grpc.correlation import GRPC_CORRELATION_ID_KEY
from src.backend.entrypoints.grpc.correlation import (
    extract_correlation_id_from_grpc_context as _extract_correlation_id_from_grpc_context,
)


@dataclass
class _MetadataEntry:
    """Stand-in для grpc.aio.Metadata entry (key/value пара)."""

    key: str
    value: str


class _MockContext:
    """Минимальный stand-in для grpc.aio.ServicerContext."""

    def __init__(self, metadata: Any) -> None:
        self._metadata = metadata

    def invocation_metadata(self) -> Any:
        return self._metadata


def test_no_context_returns_empty_string() -> None:
    assert _extract_correlation_id_from_grpc_context(None) == ""


def test_context_without_metadata_method_returns_empty() -> None:
    class _NoMeta:
        pass

    assert _extract_correlation_id_from_grpc_context(_NoMeta()) == ""


def test_empty_metadata_returns_empty() -> None:
    ctx = _MockContext(metadata=[])
    assert _extract_correlation_id_from_grpc_context(ctx) == ""


def test_metadata_with_correlation_id_tuple_list() -> None:
    """Legacy grpc.aio metadata API: list[tuple[str, str]]."""
    ctx = _MockContext(
        metadata=[("authorization", "Bearer x"), ("x-correlation-id", "cid-tuple")]
    )
    assert _extract_correlation_id_from_grpc_context(ctx) == "cid-tuple"


def test_metadata_with_correlation_id_objects() -> None:
    """Modern grpc.aio metadata: list[Metadata entries with .key/.value]."""
    ctx = _MockContext(
        metadata=[
            _MetadataEntry(key="authorization", value="Bearer x"),
            _MetadataEntry(key=GRPC_CORRELATION_ID_KEY, value="cid-object"),
        ]
    )
    assert _extract_correlation_id_from_grpc_context(ctx) == "cid-object"


def test_metadata_key_case_insensitive() -> None:
    """gRPC спецификация требует lowercase, но клиент может прислать любой case."""
    ctx = _MockContext(metadata=[("X-Correlation-ID", "cid-upper")])
    assert _extract_correlation_id_from_grpc_context(ctx) == "cid-upper"


def test_metadata_other_key_returns_empty() -> None:
    ctx = _MockContext(metadata=[("trace-id", "trc-1"), ("user-agent", "test")])
    assert _extract_correlation_id_from_grpc_context(ctx) == ""


def test_invocation_metadata_returning_none_safe() -> None:
    ctx = _MockContext(metadata=None)
    assert _extract_correlation_id_from_grpc_context(ctx) == ""
