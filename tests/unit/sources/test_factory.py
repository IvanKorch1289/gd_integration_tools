"""W23 — фабрика build_source + SourceSpec."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.config.source_spec import SourceSpec, SourcesSpecFile
from src.backend.core.interfaces.source import Source, SourceKind
from src.backend.infrastructure.sources.factory import build_source


def test_spec_validates_known_kind() -> None:
    spec = SourceSpec(
        id="x", kind="webhook", action="x.y", config={"path": "/wh"}
    )
    assert spec.kind is SourceKind.WEBHOOK
    assert spec.idempotency is True


def test_spec_rejects_unknown_kind() -> None:
    with pytest.raises(Exception):
        SourceSpec(id="x", kind="kludge", action="x.y")


def test_specfile_empty() -> None:
    f = SourcesSpecFile()
    assert f.sources == []


@pytest.mark.parametrize(
    ("kind", "config"),
    [
        ("webhook", {"path": "/wh"}),
        ("http", {"path": "/api/inbound"}),
        ("file_watcher", {"directory": "/tmp"}),  # noqa: S108
        ("polling", {"url": "http://x", "interval_seconds": 1.0}),
        ("websocket", {"url": "ws://x"}),
        ("soap", {"wsdl_url": "http://x?wsdl", "operation": "GetX"}),
        (
            "grpc",
            {
                "target": "localhost:50051",
                "stub_module": "fake",
                "stub_class": "Fake",
                "method": "Stream",
                "request_module": "fake",
                "request_class": "Req",
            },
        ),
        (
            "mq",
            {"transport": "redis_streams", "topic": "t1"},
        ),
        (
            "cdc",
            {"dsn": "postgres://x", "slot_name": "s1"},
        ),
    ],
)
def test_factory_constructs_all_kinds(kind: str, config: dict) -> None:
    spec = SourceSpec(id=f"id-{kind}", kind=kind, action="x.y", config=config)
    src = build_source(spec)
    assert isinstance(src, Source)
    assert src.source_id == f"id-{kind}"
