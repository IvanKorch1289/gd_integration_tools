"""SinkHealthMixin — backward-compat alias для ConnectorHealthMixin.

S203 W1: перенесено в ``infrastructure/clients/connector_health_mixin.py``.
Этот файл сохранён для backward-compat (``from infrastructure.sinks.base
import SinkHealthMixin``).
"""

from __future__ import annotations

from src.backend.infrastructure.clients.connector_health_mixin import (
    ConnectorHealthMixin,
)

__all__ = ("SinkHealthMixin",)


#: Alias на ConnectorHealthMixin (S203 W1 de-dup).
SinkHealthMixin = ConnectorHealthMixin