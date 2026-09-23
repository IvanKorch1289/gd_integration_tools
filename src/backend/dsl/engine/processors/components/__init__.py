"""Components processors package (S65 W1 decomp from components.py 479 LOC).

8 processor classes → 8 files (per-processor file split).

Backward-compat: ``from src.backend.dsl.engine.processors.components import HttpCallProcessor`` works.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.components.databasequeryprocessor import (  # noqa: F401 — re-export
    DatabaseQueryProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.filereadprocessor import (  # noqa: F401 — re-export
    FileReadProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.filewriteprocessor import (  # noqa: F401 — re-export
    FileWriteProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.httpcallprocessor import (  # noqa: F401 — re-export
    HttpCallProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.pollingconsumerprocessor import (  # noqa: F401 — re-export
    PollingConsumerProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.s3readprocessor import (  # noqa: F401 — re-export
    S3ReadProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.s3writeprocessor import (  # noqa: F401 — re-export
    S3WriteProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.timerprocessor import (  # noqa: F401 — re-export
    TimerProcessor,  # S65 W1: re-export
)

__all__ = (
    "DatabaseQueryProcessor",
    "FileReadProcessor",
    "FileWriteProcessor",
    "HttpCallProcessor",
    "PollingConsumerProcessor",
    "S3ReadProcessor",
    "S3WriteProcessor",
    "TimerProcessor",
)
