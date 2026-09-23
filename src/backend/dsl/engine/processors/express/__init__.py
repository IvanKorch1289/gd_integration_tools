"""Express DSL процессоры (Wave 4.2).

Публичный re-export::

    from src.backend.dsl.engine.processors.express import (
        ExpressSendProcessor,
        ExpressReplyProcessor,
        ExpressEditProcessor,
        ExpressTypingProcessor,
        ExpressSendFileProcessor,
        ExpressMentionProcessor,
        ExpressStatusProcessor,
    )
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.express.edit import ExpressEditProcessor
from src.backend.dsl.engine.processors.express.mention import ExpressMentionProcessor
from src.backend.dsl.engine.processors.express.reply import ExpressReplyProcessor
from src.backend.dsl.engine.processors.express.send import ExpressSendProcessor
from src.backend.dsl.engine.processors.express.send_file import ExpressSendFileProcessor
from src.backend.dsl.engine.processors.express.status import ExpressStatusProcessor
from src.backend.dsl.engine.processors.express.typing import ExpressTypingProcessor

__all__ = (
    "ExpressEditProcessor",
    "ExpressMentionProcessor",
    "ExpressReplyProcessor",
    "ExpressSendFileProcessor",
    "ExpressSendProcessor",
    "ExpressStatusProcessor",
    "ExpressTypingProcessor",
)
