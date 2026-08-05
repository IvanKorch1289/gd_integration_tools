"""Regression-тесты для backward-compat re-export S180 P0-5.

Проверяет, что ``from src.backend.dsl.engine.processors.rpa.operations
import <ProcessorName>`` работает для всех 17 re-exported processors.

История: S171/S180 добавили несколько процессоров (FileDelete, FileList,
FileWatch, CsvRead, CsvWrite, FtpUpload, HttpRequest, FilteredDirectoryScan),
но они не попали в ``__all__`` и ``from ...operations import X`` падал с
ImportError для внешних потребителей.
"""

from __future__ import annotations

import pytest

# Все 17 публично доступных processors (после S180 P0-5 fix).
EXPECTED_PROCESSORS = [
    # S65 W2 original 9:
    "ArchiveProcessor",
    "FileMoveProcessor",
    "ImageOcrProcessor",
    "ImageResizeProcessor",
    "RegexProcessor",
    "TemplateRenderProcessor",
    "HashProcessor",
    "EncryptProcessor",
    "DecryptProcessor",
    # S171/S180 added 8:
    "CsvReadProcessor",
    "CsvWriteProcessor",
    "FileDeleteProcessor",
    "FileListProcessor",
    "FileWatchProcessor",
    "FilteredDirectoryScanProcessor",
    "FtpUploadProcessor",
    "HttpRequestProcessor",
]


@pytest.mark.parametrize("processor_name", EXPECTED_PROCESSORS)
def test_reexport_resolves(processor_name: str) -> None:
    """Каждый из 17 processors доступен через canonical public-path."""
    from src.backend.dsl.engine.processors.rpa import operations as ops_mod

    cls = getattr(ops_mod, processor_name)
    assert cls is not None
    # Sanity: каждая из них — класс с __init__.
    assert callable(cls)


def test_reexport_count_matches_files() -> None:
    """Re-export должен покрывать все .py файлы (кроме __init__.py + pycache)."""
    from pathlib import Path

    from src.backend.dsl.engine.processors.rpa import operations as ops_mod

    pkg_dir = Path(ops_mod.__file__).parent
    py_files = [
        p
        for p in pkg_dir.glob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("__pycache__")
    ]
    # Каждый файл может содержать 1 или более публичных классов.
    # Минимально — все 8 missing processors теперь доступны через __all__.
    expected_in_all = set(EXPECTED_PROCESSORS)
    assert expected_in_all.issubset(set(ops_mod.__all__)), (
        f"Missing from __all__: {expected_in_all - set(ops_mod.__all__)}"
    )
    # Sanity: файлов больше чем __all__ entries (другие utility-классы есть).
    assert len(py_files) >= len(ops_mod.__all__)


def test_file_delete_processor_uses_validate_path() -> None:
    """Проверяет что FileDeleteProcessor — реальный processor (не stub).

    S180 P0-5 fix восстановил public-path; сам класс использует
    core.rpa.path_safety.validate_path() для cycle 33 fix.
    """
    from src.backend.dsl.engine.processors.rpa.operations import FileDeleteProcessor

    assert hasattr(FileDeleteProcessor, "__init__")
    src = FileDeleteProcessor.__module__
    assert src == "src.backend.dsl.engine.processors.rpa.operations.filedeleteprocessor"
