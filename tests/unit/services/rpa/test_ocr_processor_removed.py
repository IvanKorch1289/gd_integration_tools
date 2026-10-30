"""ADR-0402 — мёртвый дубль OCR-процессора удалён (прецедент ADR-0100).

Каноническая реализация OCR в проекте одна — DSL-шаг ``ocr``
(``src/backend/dsl/engine/processors/rpa/operations/imageocrprocessor.py``,
класс ``ImageOcrProcessor``). Сервисная копия
(``src/backend/services/rpa/ocr_processor.py``: протокол ``OCRProcessor``,
``PytesseractOCRProcessor``, ``NoOpOCRProcessor``, фабрика
``from_environment``) не имела ни одного потребителя в ``src/`` — 0 вызовов,
0 lazy-импортов, 0 DI-регистраций.

Тест фиксирует инвариант «одна реализация OCR»:

* модуль ``services/rpa/ocr_processor.py`` отсутствует;
* ни один модуль ``src/`` его не импортирует (проверка по всему исходному
  дереву, а не по одному ``grep``);
* канонический DSL-процессор на месте и экспортируется из реестра
  процессоров.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_ROOT = _REPO_ROOT / "src"
_REMOVED_MODULE = _SRC_ROOT / "backend" / "services" / "rpa" / "ocr_processor.py"
_CANONICAL_MODULE = (
    _SRC_ROOT
    / "backend"
    / "dsl"
    / "engine"
    / "processors"
    / "rpa"
    / "operations"
    / "imageocrprocessor.py"
)


@pytest.mark.unit
class TestDeadDuplicateRemoved:
    """Мёртвый дубль OCR удалён, канон — DSL-шаг ``ocr``."""

    def test_removed_module_does_not_exist(self) -> None:
        """Файла ``services/rpa/ocr_processor.py`` больше нет."""
        assert not _REMOVED_MODULE.exists(), (
            "мёртвый дубль OCR-процессора должен быть удалён "
            "(ADR-0402, прецедент ADR-0100)"
        )

    def test_no_source_module_imports_removed_module(self) -> None:
        """Ни один модуль ``src/`` не импортирует удалённый модуль."""
        offenders: list[str] = []
        for path in _SRC_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "services.rpa.ocr_processor" in text or "rpa/ocr_processor" in text:
                # Докстринги с историей удаления допустимы — проверяем
                # импорты, а не любое упоминание.
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith(("import ", "from ")) and (
                        "ocr_processor" in stripped
                    ):
                        offenders.append(f"{path}: {stripped}")
        assert not offenders, "остались импорты удалённого модуля: " + "; ".join(
            offenders
        )

    def test_canonical_dsl_ocr_processor_still_exists(self) -> None:
        """Канон на месте: DSL-процессор ``ImageOcrProcessor``."""
        assert _CANONICAL_MODULE.exists()
        from src.backend.dsl.engine.processors.rpa import ImageOcrProcessor

        assert ImageOcrProcessor.__name__ == "ImageOcrProcessor"
