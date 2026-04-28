# ruff: noqa: S101
"""Unit-тесты ``ScanFileProcessor`` (Wave 11).

Покрывают:
    * Валидацию ``on_threat``.
    * Обязательность ``s3_key_from`` или ``data_property``.
    * Загрузку байтов из ``data_property`` (bytes / str).
    * Загрузку байтов из S3 через мок ``s3_client.get_object_bytes``.
    * Поведение ``on_threat=fail`` / ``warn`` при обнаружении угрозы.
    * Мок ``create_antivirus_backend(...).scan_bytes(...)``.
    * Round-trip ``to_spec()``.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.dsl.engine.processors.scan_file import ScanFileProcessor


def _make_exchange(
    body: Any | None = None, properties: dict[str, Any] | None = None
) -> Exchange[Any]:
    """Создаёт ``Exchange`` с заданным body и properties."""
    exchange: Exchange[Any] = Exchange(in_message=Message(body=body))
    if properties:
        exchange.properties.update(properties)
    return exchange


def _make_av_result(
    *,
    clean: bool,
    signature: str | None = None,
    backend: str = "fake",
    latency_ms: float = 1.0,
) -> MagicMock:
    """Имитирует ScanResult с нужными атрибутами."""
    result = MagicMock()
    result.clean = clean
    result.signature = signature
    result.backend = backend
    result.latency_ms = latency_ms
    return result


def _patch_factory(monkeypatch: pytest.MonkeyPatch, backend: Any) -> None:
    """Подменяет lazy-импорт ``create_antivirus_backend`` на фейк.

    ScanFileProcessor импортирует фабрику внутри ``process()``,
    поэтому подменяем сам атрибут модуля ``factory`` через
    ``sys.modules``.
    """
    fake_module = types.ModuleType("src.infrastructure.antivirus.factory")
    fake_module.create_antivirus_backend = lambda: backend  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "src.infrastructure.antivirus.factory", fake_module
    )


def _patch_s3(monkeypatch: pytest.MonkeyPatch, s3_client: Any) -> None:
    """Подменяет lazy-импорт ``s3_client`` через ``sys.modules``."""
    fake_module = types.ModuleType("src.infrastructure.clients.storage.s3_pool")
    fake_module.s3_client = s3_client  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "src.infrastructure.clients.storage.s3_pool", fake_module
    )


def _patch_metrics_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Чтобы ``_record_metric`` не пытался импортировать реальный модуль."""
    fake_module = types.ModuleType("src.infrastructure.observability.metrics")
    fake_module.record_antivirus_scan = lambda *, threat: None  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "src.infrastructure.observability.metrics", fake_module
    )


# ----------------------------- Валидация конструктора --------------------------


def test_scan_file_requires_s3_key_or_data_property() -> None:
    """Без обоих источников — ValueError."""
    with pytest.raises(ValueError, match="s3_key_from или data_property"):
        ScanFileProcessor()


@pytest.mark.parametrize("on_threat", ["fail", "warn"])
def test_scan_file_accepts_valid_on_threat(on_threat: str) -> None:
    """Валидные значения ``on_threat`` принимаются."""
    proc = ScanFileProcessor(data_property="file_data", on_threat=on_threat)
    assert proc is not None


@pytest.mark.parametrize("on_threat", ["block", "ignore", "", "FAIL"])
def test_scan_file_rejects_invalid_on_threat(on_threat: str) -> None:
    """Невалидные значения ``on_threat`` отвергаются."""
    with pytest.raises(ValueError, match="on_threat="):
        ScanFileProcessor(data_property="x", on_threat=on_threat)


def test_scan_file_default_name() -> None:
    """Имя процессора по умолчанию ``scan_file``."""
    proc = ScanFileProcessor(data_property="x")
    assert proc.name == "scan_file"


# --------------------------- Источник: data_property ---------------------------


async def test_scan_file_clean_data_property_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Чистый файл из ``data_property`` (bytes) — verdict пишется в property."""
    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock(
        return_value=_make_av_result(clean=True, backend="clamav-unix")
    )
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    proc = ScanFileProcessor(data_property="file_data", on_threat="fail")
    exchange = _make_exchange(properties={"file_data": b"hello"})
    await proc.process(exchange, MagicMock())

    fake_backend.scan_bytes.assert_awaited_once_with(b"hello")
    verdict = exchange.properties["antivirus_scan_result"]
    assert verdict["clean"] is True
    assert verdict["backend"] == "clamav-unix"
    assert exchange.status != ExchangeStatus.failed


async def test_scan_file_data_property_str_is_encoded_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """str в ``data_property`` кодируется в UTF-8."""
    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock(return_value=_make_av_result(clean=True))
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    proc = ScanFileProcessor(data_property="file_data")
    exchange = _make_exchange(properties={"file_data": "привет"})
    await proc.process(exchange, MagicMock())

    fake_backend.scan_bytes.assert_awaited_once_with("привет".encode("utf-8"))


# ----------------------------- Источник: S3 ------------------------------------


async def test_scan_file_loads_from_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если ``s3_key_from`` задан — байты грузятся через ``s3_client``."""
    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock(return_value=_make_av_result(clean=True))
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    fake_s3 = MagicMock()
    fake_s3.get_object_bytes = AsyncMock(return_value=b"s3-payload")
    _patch_s3(monkeypatch, fake_s3)

    proc = ScanFileProcessor(s3_key_from="properties.uploaded_key")
    exchange = _make_exchange(properties={"uploaded_key": "uploads/foo.bin"})
    await proc.process(exchange, MagicMock())

    fake_s3.get_object_bytes.assert_awaited_once_with("uploads/foo.bin")
    fake_backend.scan_bytes.assert_awaited_once_with(b"s3-payload")
    assert exchange.properties["antivirus_scan_result"]["clean"] is True


async def test_scan_file_s3_failure_falls_back_to_data_property(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При ошибке S3 — fallback на ``data_property``."""
    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock(return_value=_make_av_result(clean=True))
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    fake_s3 = MagicMock()
    fake_s3.get_object_bytes = AsyncMock(side_effect=RuntimeError("s3 timeout"))
    _patch_s3(monkeypatch, fake_s3)

    proc = ScanFileProcessor(
        s3_key_from="properties.key", data_property="file_data"
    )
    exchange = _make_exchange(
        properties={"key": "k1", "file_data": b"fallback-bytes"}
    )
    await proc.process(exchange, MagicMock())

    fake_backend.scan_bytes.assert_awaited_once_with(b"fallback-bytes")
    assert exchange.status != ExchangeStatus.failed


async def test_scan_file_no_payload_fails_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если данные не получены ни из S3, ни из property — fail."""
    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock()
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    proc = ScanFileProcessor(data_property="file_data")
    exchange = _make_exchange(properties={})  # property отсутствует
    await proc.process(exchange, MagicMock())

    assert exchange.status == ExchangeStatus.failed
    assert "не удалось получить байты" in (exchange.error or "")
    fake_backend.scan_bytes.assert_not_awaited()


# ---------------------------- on_threat поведение ------------------------------


@pytest.mark.parametrize(
    ("clean", "on_threat", "should_fail"),
    [
        (True, "fail", False),
        (True, "warn", False),
        (False, "fail", True),
        (False, "warn", False),
    ],
)
async def test_scan_file_on_threat_behaviour(
    monkeypatch: pytest.MonkeyPatch,
    clean: bool,
    on_threat: str,
    should_fail: bool,
) -> None:
    """Матрица: clean × on_threat → exchange.failed?"""
    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock(
        return_value=_make_av_result(
            clean=clean,
            signature=None if clean else "EICAR-Test-File",
            backend="clamav",
        )
    )
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    proc = ScanFileProcessor(data_property="file_data", on_threat=on_threat)
    exchange = _make_exchange(properties={"file_data": b"payload"})
    await proc.process(exchange, MagicMock())

    if should_fail:
        assert exchange.status == ExchangeStatus.failed
        assert exchange.error is not None
        assert "обнаружена угроза" in exchange.error
    else:
        assert exchange.status != ExchangeStatus.failed

    verdict = exchange.properties["antivirus_scan_result"]
    assert verdict["clean"] is clean
    if not clean:
        assert verdict["signature"] == "EICAR-Test-File"


async def test_scan_file_threat_warn_logs_does_not_fail(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``on_threat=warn`` — пишет warning в лог, не валит exchange."""
    import logging

    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock(
        return_value=_make_av_result(
            clean=False, signature="EICAR", backend="clamav"
        )
    )
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    proc = ScanFileProcessor(data_property="file_data", on_threat="warn")
    exchange = _make_exchange(properties={"file_data": b"x"})

    with caplog.at_level(logging.WARNING, logger="dsl.scan_file"):
        await proc.process(exchange, MagicMock())

    assert exchange.status != ExchangeStatus.failed
    assert any("угроза обнаружена" in rec.message for rec in caplog.records)


# ----------------------------- AV-бэкенд недоступен ---------------------------


async def test_scan_file_backend_unavailable_fail_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если AV-бэкенд кидает исключение и ``on_threat=fail`` — exchange.fail."""
    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock(side_effect=RuntimeError("clamav down"))
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    proc = ScanFileProcessor(data_property="file_data", on_threat="fail")
    exchange = _make_exchange(properties={"file_data": b"x"})
    await proc.process(exchange, MagicMock())

    assert exchange.status == ExchangeStatus.failed
    assert "AV-бэкенд недоступен" in (exchange.error or "")
    assert "antivirus_scan_result_error" in exchange.properties


async def test_scan_file_backend_unavailable_warn_mode_does_not_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``on_threat=warn`` + бэкенд недоступен → не валит exchange."""
    fake_backend = MagicMock()
    fake_backend.scan_bytes = AsyncMock(side_effect=RuntimeError("network"))
    _patch_factory(monkeypatch, fake_backend)
    _patch_metrics_noop(monkeypatch)

    proc = ScanFileProcessor(data_property="file_data", on_threat="warn")
    exchange = _make_exchange(properties={"file_data": b"x"})
    await proc.process(exchange, MagicMock())

    assert exchange.status != ExchangeStatus.failed
    assert "antivirus_scan_result_error" in exchange.properties


# --------------------------------- to_spec() -----------------------------------


def test_scan_file_to_spec_data_property_only() -> None:
    """Round-trip ``to_spec()`` для ``data_property``."""
    proc = ScanFileProcessor(
        data_property="upload_bytes",
        on_threat="warn",
        result_property="av_result",
    )
    spec = proc.to_spec()

    assert "scan_file" in spec
    inner = spec["scan_file"]
    assert inner["data_property"] == "upload_bytes"
    assert inner["on_threat"] == "warn"
    assert inner["result_property"] == "av_result"
    assert "s3_key_from" not in inner


def test_scan_file_to_spec_s3_only() -> None:
    """Round-trip ``to_spec()`` для S3-источника."""
    proc = ScanFileProcessor(s3_key_from="properties.uploaded_key")
    spec = proc.to_spec()
    inner = spec["scan_file"]

    assert inner["s3_key_from"] == "properties.uploaded_key"
    assert inner["on_threat"] == "fail"
    assert inner["result_property"] == "antivirus_scan_result"
    assert "data_property" not in inner


def test_scan_file_to_spec_roundtrip_reconstruct() -> None:
    """Пересоздание из ``to_spec()`` сохраняет идентичный spec."""
    original = ScanFileProcessor(
        s3_key_from="properties.key",
        data_property="bytes_property",
        on_threat="warn",
        result_property="my_av_result",
    )
    spec = original.to_spec()
    inner = spec["scan_file"]

    reconstructed = ScanFileProcessor(
        s3_key_from=inner.get("s3_key_from"),
        data_property=inner.get("data_property"),
        on_threat=inner["on_threat"],
        result_property=inner["result_property"],
    )
    assert reconstructed.to_spec() == spec
