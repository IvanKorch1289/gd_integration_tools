"""Sink publish processors package (S57 W4 decomp from sink_publish.py 561 LOC).

6 processor classes + 1 spec + 2 helpers decomposed в 3 files (per protocol family):
- ``protocols.py``: GrpcCallProcessor, SoapCallProcessor (RPC)
- ``messaging.py``: MqPublishProcessor, WsPublishProcessor, MqttPublishProcessor (messaging)
- ``generic.py``: GenericSinkPublishProcessor + _OutSpec + _resolve_payload + _store_result

Backward-compat: ``from src.backend.dsl.engine.processors.sink_publish import GrpcCallProcessor`` works.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.sink_publish.protocols import GrpcCallProcessor  # S57 W4: re-export
from src.backend.dsl.engine.processors.sink_publish.protocols import SoapCallProcessor  # S57 W4: re-export
from src.backend.dsl.engine.processors.sink_publish.messaging import MqPublishProcessor  # S57 W4: re-export
from src.backend.dsl.engine.processors.sink_publish.messaging import WsPublishProcessor  # S57 W4: re-export
from src.backend.dsl.engine.processors.sink_publish.messaging import MqttPublishProcessor  # S57 W4: re-export
from src.backend.dsl.engine.processors.sink_publish.generic import GenericSinkPublishProcessor  # S57 W4: re-export
from src.backend.dsl.engine.processors.sink_publish.generic import _OutSpec  # S57 W4: re-export
from src.backend.dsl.engine.processors.sink_publish.generic import _resolve_payload  # S57 W4: re-export
from src.backend.dsl.engine.processors.sink_publish.generic import _store_result  # S57 W4: re-export

__all__ = (
    "_OutSpec",
    "GenericSinkPublishProcessor",
    "GrpcCallProcessor",
    "SoapCallProcessor",
    "MqPublishProcessor",
    "WsPublishProcessor",
    "MqttPublishProcessor",
    "_resolve_payload",
    "_store_result",
)
