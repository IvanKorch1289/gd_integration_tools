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

from __future__ import annotations as annotations

from src.backend.dsl.engine.processors.telegram.edit import (
    TelegramEditProcessor,  # noqa: F401 — re-export
)
from src.backend.dsl.engine.processors.telegram.mention import (
    TelegramMentionProcessor,  # noqa: F401 — re-export
)
from src.backend.dsl.engine.processors.telegram.reply import (
    TelegramReplyProcessor,  # noqa: F401 — re-export
)
from src.backend.dsl.engine.processors.telegram.send import (
    TelegramSendProcessor,  # noqa: F401 — re-export
)
from src.backend.dsl.engine.processors.telegram.send_file import (
    TelegramSendFileProcessor,
)
from src.backend.dsl.engine.processors.telegram.status import (
    TelegramStatusProcessor,  # noqa: F401 — re-export
)
from src.backend.dsl.engine.processors.telegram.typing import (
    TelegramTypingProcessor,  # noqa: F401 — re-export
)

__all__ = (
    "TelegramEditProcessor",
    "TelegramMentionProcessor",
    "TelegramReplyProcessor",
    "TelegramSendFileProcessor",
    "TelegramSendProcessor",
    "TelegramStatusProcessor",
    "TelegramTypingProcessor",
)
