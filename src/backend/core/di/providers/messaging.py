"""Messaging providers — telegram bot, express chatbot, dialogs repo.

W9 P2-13 Phase 2 (cycle 153, MINIMAX plan): извлечено из
``core/di/providers/cache.py`` (868 LOC god-module). Telegram и Express —
chatbot/messaging concerns, не cache.

Back-compat: ``core/di/providers/cache.py`` продолжает re-export этих
функций через lazy ``__getattr__`` proxy (см. ADR-0321).

Singleton cache ``_overrides`` is per-domain (NOT shared) — каждый domain
имеет свой override-словарь для изоляции тестов.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


# ─── S85 M2-#11 accelerated batch: telegram_bot provider ───────


def get_telegram_bot_provider() -> Any:
    """Возвращает telegram_bot singleton (aiogram-based).

    S85 accelerated batch: lazy resolve для 6 telegram/* файлов.
    W9 P2-13 Phase 2: перенесено из cache.py → messaging.py.
    """
    if "telegram_bot" in _overrides:
        return _overrides["telegram_bot"]
    module = resolve_module("clients.external.telegram_bot")
    return module


def set_telegram_bot_provider(bot: Any) -> None:
    """Test-override для telegram_bot module (Sprint 85+, W9 P2-13 Phase 2)."""
    _overrides["telegram_bot"] = bot


# ─── S87 M2-#11 final batch: express bot providers ─────────────


def get_express_bot_module_provider() -> Any:
    r"""Возвращает \`express_bot\` module (external).

    S87 (legacy): lazy resolve для 4 express/* файлов.
    W9 P2-13 Phase 2: перенесено из cache.py → messaging.py.
    """
    if "express_bot_module" in _overrides:
        return _overrides["express_bot_module"]
    module = resolve_module("clients.external.express_bot")
    return module


def set_express_bot_module_provider(module: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["express_bot_module"] = module


def get_express_dialogs_mongo_provider() -> Any:
    """Возвращает ExpressBotDialogsRepository (Mongo-backed).

    S87 (legacy): lazy resolve для express/_common.py.
    W9 P2-13 Phase 2: перенесено из cache.py → messaging.py.
    """
    if "express_dialogs_mongo" in _overrides:
        return _overrides["express_dialogs_mongo"]
    module = resolve_module("repositories.express_dialogs_mongo")
    return module


def set_express_dialogs_mongo_provider(repo: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["express_dialogs_mongo"] = repo


__all__ = (
    "get_express_bot_module_provider",
    "get_express_dialogs_mongo_provider",
    "get_telegram_bot_provider",
    "set_express_bot_module_provider",
    "set_express_dialogs_mongo_provider",
    "set_telegram_bot_provider",
)
