"""Messaging providers — reply_channel + sinks (W9 P2-13 Phase 7).

W9 P2-13 Phase 7 (cycle 153): извлечено из ``core/di/providers/workflow.py``
(602 LOC god-module). Содержит ReplyChannel + Sink factory + 4 sink classes
(MQ, WS, gRPC, SOAP).

Back-compat: ``core/di/providers/workflow.py`` (file) продолжает re-export
все 6 funcs через thin ``__init__.py`` shim (см. ADR-0331).

Singleton cache ``_overrides`` is per-domain (NOT shared).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


# ─── W9 P2-13 Phase 2: sinks + DLQ + reply_channel providers (migrated from cache.py) ──────────


def get_reply_channel_class_provider() -> Any:
    r"""Возвращает :class:\`ReplyChannel\` class (singleton via \`instance()\`).

    S73 M2-#11 batch 8: lazy resolve для dsl/processors/request_reply.py.
    ReplyChannel — class с classmethod \`instance()\` (singleton).
    Caller делает \`ReplyChannel.instance()\` для получения singleton.

    W9 P2-13 Phase 7: перенесено в workflow/_messaging.py (messaging = workflow concern).
    """
    if "reply_channel_class" in _overrides:
        return _overrides["reply_channel_class"]
    module = resolve_module("clients.messaging.reply_channel")
    return module.ReplyChannel


def set_reply_channel_class_provider(channel_class: Any) -> None:
    """Установить override для ``reply_channel_class`` provider."""
    _overrides["reply_channel_class"] = channel_class


def get_sink_factory_provider() -> Any:
    r"""Возвращает \`build_sink\` (sink factory).

    S87 (legacy): lazy resolve для sink_publish/generic.py.
    W9 P2-13 Phase 7: перенесено в workflow/_messaging.py.
    """
    if "sink_factory" in _overrides:
        return _overrides["sink_factory"]
    module = resolve_module("sinks.factory")
    return module.build_sink


def set_sink_factory_provider(factory: Any) -> None:
    """Установить override для ``sink_factory`` provider."""
    _overrides["sink_factory"] = factory


def get_mq_sink_class_provider() -> Any:
    r"""Возвращает :class:\`MqSink\` (messaging queue sink).

    S87 (legacy): lazy resolve для sink_publish/messaging.py.
    W9 P2-13 Phase 7: перенесено в workflow/_messaging.py.
    """
    if "mq_sink_class" in _overrides:
        return _overrides["mq_sink_class"]
    module = resolve_module("sinks.mq_sink")
    return module.MqSink


def set_mq_sink_class_provider(aclass: Any) -> None:
    """Установить override для ``mq_sink_class`` provider."""
    _overrides["mq_sink_class"] = aclass


def get_ws_sink_class_provider() -> Any:
    r"""Возвращает :class:\`WsSink\` (WebSocket sink)."""
    if "ws_sink_class" in _overrides:
        return _overrides["ws_sink_class"]
    module = resolve_module("sinks.ws_sink")
    return module.WsSink


def set_ws_sink_class_provider(aclass: Any) -> None:
    """Установить override для ``ws_sink_class`` provider."""
    _overrides["ws_sink_class"] = aclass


def get_grpc_sink_class_provider() -> Any:
    r"""Возвращает :class:\`GrpcSink\` (gRPC sink)."""
    if "grpc_sink_class" in _overrides:
        return _overrides["grpc_sink_class"]
    module = resolve_module("sinks.grpc_sink")
    return module.GrpcSink


def set_grpc_sink_class_provider(aclass: Any) -> None:
    """Установить override для ``grpc_sink_class`` provider."""
    _overrides["grpc_sink_class"] = aclass


def get_soap_sink_class_provider() -> Any:
    r"""Возвращает :class:\`SoapSink\` (SOAP sink)."""
    if "soap_sink_class" in _overrides:
        return _overrides["soap_sink_class"]
    module = resolve_module("sinks.soap_sink")
    return module.SoapSink


def set_soap_sink_class_provider(aclass: Any) -> None:
    """Установить override для ``soap_sink_class`` provider."""
    _overrides["soap_sink_class"] = aclass
