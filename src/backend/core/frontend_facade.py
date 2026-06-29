"""Frontend facade для core/ (D271, M24 P0 architecture).

Ponytail YAGNI: thin wrapper re-export core symbols.
"""
from __future__ import annotations

from src.backend.core.config.express import express_settings
from src.backend.core.config.features import feature_flags
from src.backend.core.di.providers import (
    get_express_bot_client_factory_provider,
    get_express_botx_message_class_provider,
)
from src.backend.core.logging import get_logger
from src.backend.core.messaging import (
    FakeOutbox,
    OutboxBackend,
    OutboxEvent,
)

__all__ = (
    "express_settings",
    "feature_flags",
    "get_logger",
    "get_express_bot_client_factory_provider",
    "get_express_botx_message_class_provider",
    "FakeOutbox",
    "OutboxBackend",
    "OutboxEvent",
)
