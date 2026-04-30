"""ScanFileProcessor (Wave 11) — антивирусная проверка файла в DSL.

Использует :class:`AntivirusBackend` (Wave 2.4) — фабрика
:func:`create_antivirus_backend` собирает цепочку
ClamAV unix → TCP → HTTP fallback. Hash-кэш (Redis) применяется
автоматически в фабрике.

Источники файла (в порядке приоритета):

1. ``s3_key_from`` — выражение, возвращающее S3-ключ;
   файл скачивается через ``s3_client.get_object_bytes``.
2. ``data_property`` — exchange-property с готовыми ``bytes``.

При обнаружении угрозы (``clean=False``):

* если ``on_threat='fail'`` — exchange.fail() с описанием сигнатуры;
* если ``on_threat='warn'`` — событие пишется в metric/log, exchange
  продолжает выполнение; результат сохраняется в property.

Использование в YAML::

    - scan_file:
        s3_key_from: properties.uploaded_key
        on_threat: fail
        result_property: av_scan_result
"""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.entity import _resolve

__all__ = ("ScanFileProcessor",)

_logger = logging.getLogger("dsl.scan_file")

_VALID_ON_THREAT = frozenset({"fail", "warn"})


class ScanFileProcessor(BaseProcessor):
    """Сканирует файл AV-бэкендом и сохраняет вердикт в exchange-property.

    Args:
        s3_key_from: Выражение S3-ключа (опционально).
        data_property: Имя exchange-property с ``bytes`` (опционально).
        on_threat: ``fail`` (default) | ``warn`` — поведение при угрозе.
        result_property: Имя property для записи структуры
            ``{clean, signature, backend, latency_ms}``.
    """

    def __init__(
        self,
        *,
        s3_key_from: str | None = None,
        data_property: str | None = None,
        on_threat: str = "fail",
        result_property: str = "antivirus_scan_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "scan_file")
        if not s3_key_from and not data_property:
            raise ValueError("ScanFileProcessor: укажите s3_key_from или data_property")
        if on_threat not in _VALID_ON_THREAT:
            raise ValueError(
                f"ScanFileProcessor: on_threat={on_threat!r} не из "
                f"{sorted(_VALID_ON_THREAT)}"
            )
        self._s3_key_from = s3_key_from
        self._data_property = data_property
        self._on_threat = on_threat
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Извлекает байты файла, сканирует, сохраняет вердикт."""
        payload = await self._load_bytes(exchange)
        if payload is None:
            exchange.fail("ScanFileProcessor: не удалось получить байты файла")
            return

        try:
            from src.infrastructure.antivirus.factory import create_antivirus_backend

            backend = create_antivirus_backend()
            result = await backend.scan_bytes(payload)
        except Exception as exc:
            _logger.warning("ScanFileProcessor: AV-бэкенд недоступен: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))
            if self._on_threat == "fail":
                exchange.fail(f"ScanFileProcessor: AV-бэкенд недоступен: {exc}")
            return

        verdict = {
            "clean": result.clean,
            "signature": result.signature,
            "backend": result.backend,
            "latency_ms": result.latency_ms,
        }
        exchange.set_property(self._result_property, verdict)

        if not result.clean:
            _logger.warning(
                "ScanFile: угроза обнаружена backend=%s signature=%s",
                result.backend,
                result.signature,
            )
            self._record_metric(threat=True)
            if self._on_threat == "fail":
                exchange.fail(
                    f"ScanFileProcessor: обнаружена угроза "
                    f"signature={result.signature!r}"
                )
            return
        self._record_metric(threat=False)

    async def _load_bytes(self, exchange: Exchange[Any]) -> bytes | None:
        """Загружает файл из источника-приоритета: S3 → exchange-property."""
        if self._s3_key_from:
            key = _resolve(exchange, self._s3_key_from)
            if key:
                try:
                    from src.infrastructure.clients.storage.s3_pool import s3_client

                    data = await s3_client.get_object_bytes(str(key))
                    if data is not None:
                        return data
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "ScanFile: S3 read для key=%r упал: %s — fallback property",
                        key,
                        exc,
                    )

        if self._data_property:
            data = exchange.properties.get(self._data_property)
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                return data.encode("utf-8")
        return None

    @staticmethod
    def _record_metric(*, threat: bool) -> None:
        """Best-effort метрика; ``infrastructure.observability.metrics``
        может быть недоступен в тестах."""
        try:
            from src.infrastructure.observability.metrics import record_antivirus_scan

            record_antivirus_scan(threat=threat)
        except Exception:  # noqa: BLE001, S110
            pass

    def to_spec(self) -> dict:
        """YAML-spec round-trip."""
        spec: dict[str, Any] = {
            "on_threat": self._on_threat,
            "result_property": self._result_property,
        }
        if self._s3_key_from is not None:
            spec["s3_key_from"] = self._s3_key_from
        if self._data_property is not None:
            spec["data_property"] = self._data_property
        return {"scan_file": spec}
