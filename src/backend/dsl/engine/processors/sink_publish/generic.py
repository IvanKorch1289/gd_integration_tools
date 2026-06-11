"""S57 W4 — generic.py part of sink_publish decomp.

Classes: GenericSinkPublishProcessor, _OutSpec.

generic sink + shared spec + helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error


@dataclass(slots=True)
class GenericSinkPublishProcessor(BaseProcessor):
    """``.sink_publish(kind=..., config={...})`` — обобщённый sink publisher.

    Использует :func:`~src.backend.infrastructure.sinks.factory.build_sink`
    для построения Sink-экземпляра из declarative-spec и публикует
    payload через ``Sink.send(payload)``. Симметрия с Sink-классами
    в :mod:`infrastructure.sinks` без дублирования специализированных
    PublishProcessor-ов для gRPC/SOAP/MQ/WS/MQTT.

    Args:
        kind: Один из ``"http"`` / ``"webhook"`` / ``"file"`` /
            ``"email"`` / ``"s3"`` (новые Sink-методы Sprint 3 W1 K3).
        config: Конкретные параметры Sink-класса (без ``sink_id`` и
            ``kind`` — они выставляются автоматически).
        payload_property: Откуда брать payload (None → ``in_message.body``).
        result_property: Куда писать результат публикации.
    """

    def __init__(
        self,
        *,
        kind: str,
        config: dict[str, Any],
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
        name: str | None = None,
    ) -> None:
        if kind not in _GENERIC_SINK_KINDS:
            allowed = ", ".join(sorted(_GENERIC_SINK_KINDS))
            raise ValueError(
                f"sink_publish: kind must be one of {allowed}, got {kind!r}"
            )
        super().__init__(name=name or f"sink_publish:{kind}")
        self._kind = kind
        self._config = dict(config)
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Конструирует Sink через factory и публикует ``payload``."""
        from src.backend.infrastructure.sinks.factory import build_sink

        spec: dict[str, Any] = {
            "sink_id": self.name or f"sink_publish:{self._kind}",
            "kind": self._kind,
            **self._config,
        }
        try:
            sink = build_sink(spec)
        except ValueError as exc:
            _store_result(exchange, self._out, {"ok": False, "error": str(exc)})
            return

        payload = _resolve_payload(exchange, self._payload_property)
        result = await sink.send(payload)
        _store_result(exchange, self._out, {"ok": result.ok, **result.details})

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "kind": self._kind,
            "config": dict(self._config),
            "result_property": self._out.result_property,
        }
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"sink_publish": spec}


class _OutSpec:
    """Конфигурация сохранения результата в exchange (общая для всех Sink-процессоров).

    Attributes:
        result_property: Имя property в ``exchange.properties``.
        set_out: Записать результат также в ``exchange.out_message`` (default).
    """

    result_property: str
    set_out: bool = True


def _resolve_payload(exchange: Exchange[Any], payload_property: str | None) -> Any:
    """Извлекает payload из exchange (по property или из in_message.body)."""
    if payload_property:
        return exchange.properties.get(payload_property, exchange.in_message.body)
    return exchange.in_message.body


def _store_result(exchange: Exchange[Any], spec: _OutSpec, result: Any) -> None:
    """Сохраняет result в property и опционально в out_message."""
    exchange.set_property(spec.result_property, result)
    if spec.set_out:
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
