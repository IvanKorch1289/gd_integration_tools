"""ADR-0390 (волна 18, кластер G1) — CSV-инъекция в FileWriteProcessor.

Дефект (10) [medium]: ADR-0367 закрыл формулы в ``CsvWriteProcessor``, но
``FileWriteProcessor`` (ветка ``format="csv"``) писал значения и заголовки
«как есть» — та же CSV-инъекция (OWASP CSV Injection): ячейка
``=cmd|'/c calc'!A0`` исполнялась как формула в Excel/LibreOffice.

Фикс: переиспользован канон ``processors/_csv_safety.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


def _exchange(body: Any = None) -> MagicMock:
    ex = MagicMock()
    ex.in_message = MagicMock()
    ex.in_message.body = {} if body is None else body
    ex.properties = {}
    ex.set_property = MagicMock()
    ex.set_error = MagicMock()
    ex.stop = MagicMock()
    ex.fail = MagicMock()
    return ex


@pytest.mark.asyncio
async def test_csv_values_are_neutralized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(10) Значение-формула получает префикс ``'``."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    dst = tmp_path / "out.csv"

    from src.backend.dsl.engine.processors.components.filewriteprocessor import (
        FileWriteProcessor,
    )

    proc = FileWriteProcessor(path=str(dst))
    ex = _exchange([{"name": "=cmd|'/c calc'!A0", "qty": "1"}])

    await proc.process(ex, MagicMock())

    ex.fail.assert_not_called()
    content = dst.read_text()
    assert "'=cmd|'/c calc'!A0" in content
    assert "\n=cmd" not in content


@pytest.mark.asyncio
async def test_csv_headers_are_neutralized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(10) Заголовок-формула тоже нейтрализуется (header — тоже ячейка)."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    dst = tmp_path / "out.csv"

    from src.backend.dsl.engine.processors.components.filewriteprocessor import (
        FileWriteProcessor,
    )

    proc = FileWriteProcessor(path=str(dst))
    ex = _exchange([{"=SUM(A1:A2)": "1"}])

    await proc.process(ex, MagicMock())

    ex.fail.assert_not_called()
    content = dst.read_text()
    assert "'=SUM(A1:A2)" in content


@pytest.mark.asyncio
async def test_numeric_values_are_not_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сан-санк: числа и обычные строки не изменяются."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    dst = tmp_path / "out.csv"

    from src.backend.dsl.engine.processors.components.filewriteprocessor import (
        FileWriteProcessor,
    )

    proc = FileWriteProcessor(path=str(dst))
    ex = _exchange([{"name": "Иван", "qty": 5}])

    await proc.process(ex, MagicMock())

    ex.fail.assert_not_called()
    content = dst.read_text()
    assert "Иван" in content
    assert "5" in content
    assert "'" not in content
