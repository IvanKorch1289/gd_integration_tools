"""RPA operations package (S65 W2 decomp from rpa/operations.py 478 LOC).

9 processor classes → 9 files (per-processor file split).
S171/S180 expansion: +8 processors (CsvRead/Write, FileDelete/List/Watch,
FilteredDirectoryScan, FtpUpload, HttpRequest).

Backward-compat: ``from src.backend.dsl.engine.processors.rpa.operations import FileMoveProcessor``
and ``FileDeleteProcessor`` etc. work — все 17 процессоров re-exported.

S180 P0-5 (S36 multi-agent audit, general-8): 7 S171 processors были
в files но НЕ в ``__all__`` → external ``from src.backend.dsl.engine.processors.rpa.operations
import FileDeleteProcessor`` падал с ImportError. Все 8 missing добавляются
ниже (1 дополнительный — FilteredDirectoryScanProcessor из D166).
"""

from __future__ import annotations as annotations

from src.backend.dsl.engine.processors.rpa.operations.archiveprocessor import (
    ArchiveProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.csvreadprocessor import (
    CsvReadProcessor,  # S180 P0-5: S171 re-export
)
from src.backend.dsl.engine.processors.rpa.operations.csvwriteprocessor import (
    CsvWriteProcessor,  # S180 P0-5: S171 re-export
)
from src.backend.dsl.engine.processors.rpa.operations.decryptprocessor import (
    DecryptProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.encryptprocessor import (
    EncryptProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.filedeleteprocessor import (
    FileDeleteProcessor,  # S180 P0-5: S171 re-export
)
from src.backend.dsl.engine.processors.rpa.operations.filelistprocessor import (
    FileListProcessor,  # S180 P0-5: S171 re-export
)
from src.backend.dsl.engine.processors.rpa.operations.filemoveprocessor import (
    FileMoveProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.filewatchprocessor import (
    FileWatchProcessor,  # S180 P0-5: S171 re-export
)
from src.backend.dsl.engine.processors.rpa.operations.filtereddirectoryscanprocessor import (
    FilteredDirectoryScanProcessor,  # S180 P0-5: D166 re-export
)
from src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor import (
    FtpUploadProcessor,  # S180 P0-5: S171 re-export
)
from src.backend.dsl.engine.processors.rpa.operations.hashprocessor import (
    HashProcessor,  # S65 W2: re-export
)
from src.backend.dsl.engine.processors.rpa.operations.httprequestprocessor import (
    HttpRequestProcessor,  # S180 P0-5: S171 re-export
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
    "ArchiveProcessor",
    # S171/S180 добавлены для backward-compat после operations split:
    "CsvReadProcessor",
    "CsvWriteProcessor",
    "DecryptProcessor",
    "EncryptProcessor",
    "FileDeleteProcessor",
    "FileListProcessor",
    "FileMoveProcessor",
    "FileWatchProcessor",
    "FilteredDirectoryScanProcessor",
    "FtpUploadProcessor",
    "HashProcessor",
    "HttpRequestProcessor",
    "ImageOcrProcessor",
    "ImageResizeProcessor",
    "RegexProcessor",
    "TemplateRenderProcessor",
)
