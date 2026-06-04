"""Unit-тесты PdfTemplateProcessor — Wave [wave:s5/k3-w2-processor-pack-2]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.pdf_template import PdfTemplateProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_pdf_template", True)


@pytest.mark.asyncio
async def test_render_simple_pdf() -> None:
    pytest.importorskip("reportlab")
    proc = PdfTemplateProcessor(
        template="Order #{{ id }} for {{ customer }}", to="body.pdf"
    )
    ex = _ex({"id": 42, "customer": "Acme"})

    await proc.process(ex, AsyncMock())

    pdf_bytes = ex.in_message.body["pdf"]
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_render_multiline() -> None:
    pytest.importorskip("reportlab")
    template = "Line A\nLine B\nLine C"
    proc = PdfTemplateProcessor(template=template, to="body.pdf")
    ex = _ex({})

    await proc.process(ex, AsyncMock())

    assert ex.in_message.body["pdf"].startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_pdf_template", False)
    proc = PdfTemplateProcessor(template="x", to="body.pdf")
    ex = _ex({})

    await proc.process(ex, AsyncMock())

    assert ex.properties.get("pdf_template_status") == "skipped"
