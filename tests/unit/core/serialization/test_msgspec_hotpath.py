"""Unit-тесты для msgspec hotpath serializers (S10 K2 W1)."""

from __future__ import annotations

import json

import pytest

from src.backend.core.serialization.msgspec_hotpath import (
    MSGSPEC_AVAILABLE,
    decode_json,
    encode_audit_event,
    encode_json,
    encode_ws_frame,
    hash_cache_key,
)


def test_encode_returns_bytes() -> None:
    data = encode_json({"x": 1, "y": "hello"})
    assert isinstance(data, bytes)
    assert json.loads(data) == {"x": 1, "y": "hello"}


def test_decode_accepts_bytes_and_str() -> None:
    assert decode_json(b'{"a": 1}') == {"a": 1}
    assert decode_json('{"a": 1}') == {"a": 1}


def test_roundtrip_dict() -> None:
    src = {"list": [1, 2, 3], "nested": {"k": "v"}, "n": None}
    assert decode_json(encode_json(src)) == src


def test_roundtrip_complex_unicode() -> None:
    src = {"имя": "Иван", "адрес": "Москва"}
    assert decode_json(encode_json(src)) == src


def test_hash_cache_key_deterministic() -> None:
    a = hash_cache_key("tenant=1", "route_id=x")
    b = hash_cache_key("tenant=1", "route_id=x")
    assert a == b
    assert len(a) == 16  # 16-char hex prefix


def test_hash_cache_key_changes_with_input() -> None:
    a = hash_cache_key("tenant=1")
    b = hash_cache_key("tenant=2")
    assert a != b


def test_hash_cache_key_order_matters() -> None:
    """Hash зависит от порядка частей."""
    a = hash_cache_key("a", "b")
    b = hash_cache_key("b", "a")
    assert a != b


def test_encode_ws_frame_round_trip() -> None:
    frame = encode_ws_frame({"type": "ping", "id": 42})
    payload = json.loads(frame)
    assert payload["type"] == "ping"
    assert payload["id"] == 42


def test_encode_audit_event_minimal() -> None:
    data = json.loads(encode_audit_event(action="x.created", actor="system"))
    assert data == {"action": "x.created", "actor": "system"}


def test_encode_audit_event_full() -> None:
    data = json.loads(
        encode_audit_event(
            action="login",
            actor="user-42",
            resource="session-1",
            tenant_id="tenant-A",
            extra={"ip": "1.2.3.4"},
        )
    )
    assert data["resource"] == "session-1"
    assert data["tenant_id"] == "tenant-A"
    assert data["extra"]["ip"] == "1.2.3.4"


def test_msgspec_available_constant() -> None:
    # На текущем стенде msgspec в основных deps.
    assert MSGSPEC_AVAILABLE is True
