"""Express DSL процессоры (Wave 4.2).

Публичный re-export::

    from src.dsl.engine.processors.express import (
        ExpressSendProcessor,
        ExpressReplyProcessor,
        ExpressEditProcessor,
        ExpressTypingProcessor,
    )
"""

from __future__ import annotations

from src.dsl.engine.processors.express.edit import ExpressEditProcessor
from src.dsl.engine.processors.express.reply import ExpressReplyProcessor
from src.dsl.engine.processors.express.send import ExpressSendProcessor
from src.dsl.engine.processors.express.typing import ExpressTypingProcessor

__all__ = (
    "ExpressEditProcessor",
    "ExpressReplyProcessor",
    "ExpressSendProcessor",
    "ExpressTypingProcessor",
)
