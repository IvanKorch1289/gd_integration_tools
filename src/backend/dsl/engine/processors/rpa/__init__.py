"""RPA (Robotic Process Automation) processors package (S50 W4 decomp).

16 processor classes, decomposed в ``documents.py`` / ``operations.py`` / ``system.py``
per domain.

Backward-compat: ``from src.backend.dsl.engine.processors.rpa import ArchiveProcessor``
works через re-exports ниже.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.rpa.documents import (  # S50 W4: re-export
    ExcelReadProcessor,
    PdfMergeProcessor,
    PdfReadProcessor,
    WordReadProcessor,
    WordWriteProcessor,
)
from src.backend.dsl.engine.processors.rpa.operations import (  # S50 W4: re-export
    ArchiveProcessor,
    DecryptProcessor,
    EncryptProcessor,
    FileMoveProcessor,
    HashProcessor,
    ImageOcrProcessor,
    ImageResizeProcessor,
    RegexProcessor,
    TemplateRenderProcessor,
)
from src.backend.dsl.engine.processors.rpa.system import (  # S50 W4: re-export
    EmailComposeProcessor,
    ShellExecProcessor,
)

__all__ = (
    "PdfReadProcessor",
    "PdfMergeProcessor",
    "WordReadProcessor",
    "WordWriteProcessor",
    "ExcelReadProcessor",
    "FileMoveProcessor",
    "ArchiveProcessor",
    "ImageOcrProcessor",
    "ImageResizeProcessor",
    "RegexProcessor",
    "TemplateRenderProcessor",
    "HashProcessor",
    "EncryptProcessor",
    "DecryptProcessor",
    "ShellExecProcessor",
    "EmailComposeProcessor",
)

