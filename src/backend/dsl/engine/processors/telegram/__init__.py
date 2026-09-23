"""Telegram DSL процессоры (W15.3).

Публичный re-export::

    from src.backend.dsl.engine.processors.telegram import (
        TelegramSendProcessor,
        TelegramReplyProcessor,
        TelegramEditProcessor,
        TelegramSendFileProcessor,
        TelegramTypingProcessor,
        TelegramMentionProcessor,
        TelegramStatusProcessor,
    )
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.telegram.edit import TelegramEditProcessor
from src.backend.dsl.engine.processors.telegram.mention import TelegramMentionProcessor
from src.backend.dsl.engine.processors.telegram.reply import TelegramReplyProcessor
from src.backend.dsl.engine.processors.telegram.send import TelegramSendProcessor
from src.backend.dsl.engine.processors.telegram.send_file import (
    TelegramSendFileProcessor,
)
from src.backend.dsl.engine.processors.telegram.status import TelegramStatusProcessor
from src.backend.dsl.engine.processors.telegram.typing import TelegramTypingProcessor

__all__ = (
    "TelegramEditProcessor",
    "TelegramMentionProcessor",
    "TelegramReplyProcessor",
    "TelegramSendFileProcessor",
    "TelegramSendProcessor",
    "TelegramStatusProcessor",
    "TelegramTypingProcessor",
)
