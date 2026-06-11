"""Components processors package (S65 W1 decomp from components.py 479 LOC).

8 processor classes → 8 files (per-processor file split).

Backward-compat: ``from src.backend.dsl.engine.processors.components import HttpCallProcessor`` works.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.components.databasequeryprocessor import (
    DatabaseQueryProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.filereadprocessor import (
    FileReadProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.filewriteprocessor import (
    FileWriteProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.httpcallprocessor import (
    HttpCallProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.pollingconsumerprocessor import (
    PollingConsumerProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.s3readprocessor import (
    S3ReadProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.s3writeprocessor import (
    S3WriteProcessor,  # S65 W1: re-export
)
from src.backend.dsl.engine.processors.components.timerprocessor import (
    TimerProcessor,  # S65 W1: re-export
)

__all__ = (
    "HttpCallProcessor",
    "DatabaseQueryProcessor",
    "FileReadProcessor",
    "FileWriteProcessor",
    "S3ReadProcessor",
    "S3WriteProcessor",
    "TimerProcessor",
    "PollingConsumerProcessor",
)
