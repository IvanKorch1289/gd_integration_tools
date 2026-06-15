"""S57 W4 — protocols.py part of sink_publish decomp.

Classes: GrpcCallProcessor, SoapCallProcessor.

RPC protocol processors (gRPC, SOAP).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.engine.processors.sink_publish.generic import (
    _OutSpec,
    _resolve_payload,
    _store_result,
)


@dataclass(slots=True)
class GrpcCallProcessor(BaseProcessor):
    """``.grpc_call(target, method, ...)`` — unary gRPC-вызов."""

    def __init__(
        self,
        target: str,
        full_method: str,
        *,
        secure: bool = True,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "grpc_result",
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры sink — реальный экземпляр строится при ``process``."""
        super().__init__(name=name or f"grpc_call:{full_method}")
        self._target = target
        self._full_method = full_method
        self._secure = secure
        self._timeout = timeout
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Конструирует :class:`GrpcSink` и публикует ``payload``."""
        from src.backend.infrastructure.sinks.grpc_sink import GrpcSink

        sink = GrpcSink(
            sink_id=self.name or "grpc_call",
            target=self._target,
            full_method=self._full_method,
            secure=self._secure,
            timeout=self._timeout,
        )
        payload = _resolve_payload(exchange, self._payload_property)
        result = await sink.send(payload)
        _store_result(exchange, self._out, {"ok": result.ok, **result.details})

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "target": self._target,
            "full_method": self._full_method,
            "secure": self._secure,
            "timeout": self._timeout,
            "result_property": self._out.result_property,
        }
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"grpc_call": spec}


class SoapCallProcessor(BaseProcessor):
    """``.soap_call(wsdl, operation, ...)`` — SOAP/WSDL операция через zeep."""

    def __init__(
        self,
        wsdl_url: str,
        operation: str,
        *,
        service_name: str | None = None,
        port_name: str | None = None,
        timeout: float = 30.0,
        payload_property: str | None = None,
        result_property: str = "soap_result",
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры; SOAP-клиент кэшируется внутри ``SoapSink``."""
        super().__init__(name=name or f"soap_call:{operation}")
        self._wsdl_url = wsdl_url
        self._operation = operation
        self._service_name = service_name
        self._port_name = port_name
        self._timeout = timeout
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Конструирует :class:`SoapSink` и вызывает SOAP-операцию."""
        from src.backend.infrastructure.sinks.soap_sink import SoapSink

        sink = SoapSink(
            sink_id=self.name or "soap_call",
            wsdl_url=self._wsdl_url,
            operation=self._operation,
            service_name=self._service_name,
            port_name=self._port_name,
            timeout=self._timeout,
        )
        payload = _resolve_payload(exchange, self._payload_property)
        result = await sink.send(payload)
        _store_result(exchange, self._out, {"ok": result.ok, **result.details})

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "wsdl_url": self._wsdl_url,
            "operation": self._operation,
            "timeout": self._timeout,
            "result_property": self._out.result_property,
        }
        if self._service_name is not None:
            spec["service_name"] = self._service_name
        if self._port_name is not None:
            spec["port_name"] = self._port_name
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"soap_call": spec}
