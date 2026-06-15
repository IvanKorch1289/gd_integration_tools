"""Tests для S3 DSL-процессоров (S61 W3).

Использует LocalFSStorage (без moto) через monkeypatch
``get_object_storage`` — проще и быстрее, чем aioboto3 round-trip.

Покрывает 5 процессоров: to_s3, from_s3, s3_presign, s3_delete, s3_list.

Каждый тест проверяет:
* round-trip: process() корректно мутирует exchange.properties;
* validation: type errors (key not str, data not bytes) → exchange.fail();
* безопасность: path-traversal/absolute/empty → exchange.fail();
* to_spec() round-trip (YAML serialization);
* side_effect classification.
"""

# ruff: noqa: S101  # assert — pytest idiom

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.storage.s3 import (
    FromS3Processor,
    S3DeleteProcessor,
    S3ListProcessor,
    S3PresignProcessor,
    ToS3Processor,
)
from src.backend.infrastructure.storage.local_fs import LocalFSStorage


@pytest.fixture
def fs_storage(tmp_path: Path) -> LocalFSStorage:
    """LocalFSStorage поверх tmp_path (изолировано)."""
    return LocalFSStorage(base_path=tmp_path)


@pytest.fixture
def patch_storage(fs_storage: LocalFSStorage) -> Iterator[None]:
    """Monkey-patch get_object_storage → fs_storage."""
    from src.backend.dsl.engine.processors import storage
    from src.backend.infrastructure.storage import factory

    factory.get_object_storage.cache_clear()
    original_get = storage.s3._get_storage_facade
    storage.s3._get_storage_facade = lambda context: fs_storage  # type: ignore[assignment]
    yield
    storage.s3._get_storage_facade = original_get  # type: ignore[assignment]
    factory.get_object_storage.cache_clear()


def _make_exchange(properties: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(properties=properties or {})


# ── to_s3 ─────────────────────────────────────────────────────────────────


async def test_to_s3_uploads_bytes(patch_storage: None) -> None:
    ex = _make_exchange({"payload": b"hello world", "data": "file.txt"})
    proc = ToS3Processor(data_property="payload", key_from="data")
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None
    assert "s3_key" in ex.properties


async def test_to_s3_encodes_str_to_bytes(patch_storage: None) -> None:
    """``data`` как ``str`` кодируется в UTF-8 bytes."""
    ex = _make_exchange({"text": "привет", "key": "greeting.txt"})
    proc = ToS3Processor(data_property="text", key_from="key")
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None
    assert ex.properties["s3_key"].endswith("greeting.txt")


async def test_to_s3_fails_on_invalid_key(patch_storage: None) -> None:
    ex = _make_exchange({"payload": b"x", "key": "../escape.bin"})
    proc = ToS3Processor(data_property="payload", key_from="key")
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None
    # LocalFSStorage raises "Небезопасный ключ объекта" / S3ObjectStorage raises
    # "Path-traversal" — оба варианта означают rejection.
    assert (
        "Небезопасный" in ex.error
        or "Path-traversal" in ex.error
        or "Абсолютный" in ex.error
    )


async def test_to_s3_fails_on_empty_key(patch_storage: None) -> None:
    ex = _make_exchange({"payload": b"x", "key": ""})
    proc = ToS3Processor(data_property="payload", key_from="key")
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None


async def test_to_s3_fails_on_non_bytes_data(patch_storage: None) -> None:
    ex = _make_exchange({"payload": 12345, "key": "k"})
    proc = ToS3Processor(data_property="payload", key_from="key")
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None
    assert "bytes/str" in ex.error


async def test_to_s3_fails_on_non_str_key(patch_storage: None) -> None:
    ex = _make_exchange({"payload": b"x", "key": 42})
    proc = ToS3Processor(data_property="payload", key_from="key")
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None
    assert "key must be str" in ex.error


def test_to_s3_side_effect() -> None:
    assert ToS3Processor.side_effect == SideEffectKind.SIDE_EFFECTING
    assert ToS3Processor.compensatable is False


def test_to_s3_to_spec_roundtrip() -> None:
    proc = ToS3Processor(
        data_property="x", key_from="k", content_type_from="ct", result_property="r"
    )
    spec = proc.to_spec()
    assert spec == {
        "to_s3": {
            "data_property": "x",
            "key_from": "k",
            "result_property": "r",
            "content_type_from": "ct",
        }
    }


# ── from_s3 ───────────────────────────────────────────────────────────────


async def test_from_s3_downloads_bytes(
    patch_storage: None, fs_storage: LocalFSStorage
) -> None:
    await fs_storage.upload("file.txt", b"contents")
    ex = _make_exchange({"s3_key": "file.txt"})
    proc = FromS3Processor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None
    assert ex.properties["body"] == b"contents"


async def test_from_s3_fails_on_missing_key(patch_storage: None) -> None:
    ex = _make_exchange({"s3_key": "nope.bin"})
    proc = FromS3Processor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None
    # LocalFSStorage raises OSError(ENOENT) — error message varies, just check non-empty
    assert len(ex.error) > 0


async def test_from_s3_fails_on_invalid_key(patch_storage: None) -> None:
    ex = _make_exchange({"s3_key": "/etc/passwd"})
    proc = FromS3Processor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None


async def test_from_s3_fails_on_non_str_key(patch_storage: None) -> None:
    ex = _make_exchange({"s3_key": 42})
    proc = FromS3Processor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None


def test_from_s3_side_effect() -> None:
    assert FromS3Processor.side_effect == SideEffectKind.STATEFUL


def test_from_s3_to_spec_roundtrip() -> None:
    proc = FromS3Processor(key_from="mykey", result_property="data")
    assert proc.to_spec() == {
        "from_s3": {"key_from": "mykey", "result_property": "data"}
    }


# ── s3_presign ────────────────────────────────────────────────────────────


async def test_s3_presign_returns_file_uri(
    patch_storage: None, fs_storage: LocalFSStorage
) -> None:
    await fs_storage.upload("file.txt", b"x")
    ex = _make_exchange({"s3_key": "file.txt"})
    proc = S3PresignProcessor(expires_in=60)
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None
    assert ex.properties["download_url"].startswith("file://")


async def test_s3_presign_fails_on_invalid_key(patch_storage: None) -> None:
    ex = _make_exchange({"s3_key": "../escape"})
    proc = S3PresignProcessor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None


def test_s3_presign_rejects_zero_expires() -> None:
    with pytest.raises(ValueError, match="expires_in"):
        S3PresignProcessor(expires_in=0)


def test_s3_presign_rejects_negative_expires() -> None:
    with pytest.raises(ValueError, match="expires_in"):
        S3PresignProcessor(expires_in=-1)


def test_s3_presign_side_effect() -> None:
    assert S3PresignProcessor.side_effect == SideEffectKind.PURE


def test_s3_presign_to_spec_roundtrip() -> None:
    proc = S3PresignProcessor(key_from="k", expires_in=300, result_property="url")
    assert proc.to_spec() == {
        "s3_presign": {"key_from": "k", "expires_in": 300, "result_property": "url"}
    }


# ── s3_delete ─────────────────────────────────────────────────────────────


async def test_s3_delete_removes_object(
    patch_storage: None, fs_storage: LocalFSStorage
) -> None:
    await fs_storage.upload("tmp.txt", b"x")
    ex = _make_exchange({"s3_key": "tmp.txt"})
    proc = S3DeleteProcessor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None
    assert await fs_storage.exists("tmp.txt") is False


async def test_s3_delete_idempotent_on_missing(patch_storage: None) -> None:
    ex = _make_exchange({"s3_key": "never.bin"})
    proc = S3DeleteProcessor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None


async def test_s3_delete_fails_on_invalid_key(patch_storage: None) -> None:
    ex = _make_exchange({"s3_key": ".."})
    proc = S3DeleteProcessor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None


def test_s3_delete_side_effect() -> None:
    assert S3DeleteProcessor.side_effect == SideEffectKind.SIDE_EFFECTING
    assert S3DeleteProcessor.compensatable is False


def test_s3_delete_to_spec_roundtrip() -> None:
    proc = S3DeleteProcessor(key_from="k")
    assert proc.to_spec() == {"s3_delete": {"key_from": "k"}}


# ── s3_list ───────────────────────────────────────────────────────────────


async def test_s3_list_returns_keys(
    patch_storage: None, fs_storage: LocalFSStorage
) -> None:
    await fs_storage.upload("a.bin", b"1")
    await fs_storage.upload("dir/b.bin", b"2")
    ex = _make_exchange({})
    proc = S3ListProcessor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None
    assert ex.properties["s3_keys"] == ["a.bin", "dir/b.bin"]


async def test_s3_list_with_prefix(
    patch_storage: None, fs_storage: LocalFSStorage
) -> None:
    await fs_storage.upload("a.bin", b"1")
    await fs_storage.upload("dir/b.bin", b"2")
    ex = _make_exchange({"prefix": "dir"})
    proc = S3ListProcessor(prefix_from="prefix")
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None
    assert ex.properties["s3_keys"] == ["dir/b.bin"]


async def test_s3_list_empty_bucket(patch_storage: None) -> None:
    ex = _make_exchange({})
    proc = S3ListProcessor()
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is None
    assert ex.properties["s3_keys"] == []


async def test_s3_list_fails_on_non_str_prefix(patch_storage: None) -> None:
    ex = _make_exchange({"prefix": 123})
    proc = S3ListProcessor(prefix_from="prefix")
    await proc.process(ex, context=None)  # type: ignore[arg-type]
    assert ex.error is not None


def test_s3_list_side_effect() -> None:
    assert S3ListProcessor.side_effect == SideEffectKind.STATEFUL


def test_s3_list_to_spec_roundtrip() -> None:
    proc = S3ListProcessor(prefix_from="p", result_property="r")
    assert proc.to_spec() == {"s3_list": {"result_property": "r", "prefix_from": "p"}}


def test_s3_list_to_spec_without_prefix() -> None:
    proc = S3ListProcessor()
    assert proc.to_spec() == {"s3_list": {"result_property": "s3_keys"}}


# ── registry integration ─────────────────────────────────────────────────


def test_processors_importable() -> None:
    """Smoke test: все 5 процессоров импортируются + to_spec() работает."""
    # Загружаем модуль чтобы триггернуть @processor decorator
    import src.backend.dsl.engine.processors.storage.s3  # noqa: F401

    # Если хотя бы один to_spec работает — namespace/registration ОК
    spec = ToS3Processor().to_spec()
    assert "to_s3" in spec
    spec = S3ListProcessor().to_spec()
    assert "s3_list" in spec
