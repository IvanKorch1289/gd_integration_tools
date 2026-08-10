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

from __future__ import annotations as annotations

from src.backend.dsl.engine.processors.express.edit import ExpressEditProcessor  # noqa: F401 — re-export
from src.backend.dsl.engine.processors.express.mention import ExpressMentionProcessor  # noqa: F401 — re-export
from src.backend.dsl.engine.processors.express.reply import ExpressReplyProcessor  # noqa: F401 — re-export
from src.backend.dsl.engine.processors.express.send import ExpressSendProcessor  # noqa: F401 — re-export
from src.backend.dsl.engine.processors.express.send_file import ExpressSendFileProcessor  # noqa: F401 — re-export
from src.backend.dsl.engine.processors.express.status import ExpressStatusProcessor  # noqa: F401 — re-export
from src.backend.dsl.engine.processors.express.typing import ExpressTypingProcessor  # noqa: F401 — re-export

__all__ = (
    "ExpressEditProcessor",
    "ExpressMentionProcessor",
    "ExpressReplyProcessor",
    "ExpressSendFileProcessor",
    "ExpressSendProcessor",
    "ExpressStatusProcessor",
    "ExpressTypingProcessor",
)
