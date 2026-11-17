"""Совместимый re-export DSL-моделей Exchange из ``core``.

Каноническая реализация находится в
:mod:`src.backend.core.engine.exchange`. Модуль сохранён для публичного
импорта ``from src.backend.dsl.engine.exchange import Exchange``.
"""

from __future__ import annotations

from src.backend.core.engine.exchange import Exchange as Exchange
from src.backend.core.engine.exchange import ExchangeMeta as ExchangeMeta
from src.backend.core.engine.exchange import ExchangeStatus as ExchangeStatus
from src.backend.core.engine.exchange import Message as Message
from src.backend.core.engine.exchange import (
    _make_correlation_id as _make_correlation_id,
)

__all__ = ("Exchange", "ExchangeMeta", "ExchangeStatus", "Message")
