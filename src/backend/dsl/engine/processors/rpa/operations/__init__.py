"""RPA operations package (S65 W2 decomp from rpa/operations.py 478 LOC).

9 processor classes → 9 files (per-processor file split).

Backward-compat: ``from src.backend.dsl.engine.processors.rpa.operations import FileMoveProcessor`` works.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
    ArchiveProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.decryptprocessor import (
    DecryptProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.encryptprocessor import (
    EncryptProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.filemoveprocessor import (
    FileMoveProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.hashprocessor import (
    HashProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.imageocrprocessor import (
    ImageOcrProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.imageresizeprocessor import (
    ImageResizeProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.regexprocessor import (
    RegexProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.templaterenderprocessor import (
    TemplateRenderProcessor,  # S65 W2: re-export
)

__all__ = (
    "FileMoveProcessor",
    "ArchiveProcessor",
    "ImageOcrProcessor",
    "ImageResizeProcessor",
    "RegexProcessor",
    "TemplateRenderProcessor",
    "HashProcessor",
    "EncryptProcessor",
    "DecryptProcessor",
)
