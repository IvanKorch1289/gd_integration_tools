"""Тесты HTTP-ответа SKB-эндпоинта (аудит 2026-11-20).

Дефект: ``build_skb_result_response`` сравнивал тип ответа (enum-член
``ResponseTypeChoices``) со строкой ``"PDF"`` → ветка документа не
срабатывала, клиент получал JSON вместо PDF.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.enums.skb import ResponseTypeChoices
from src.backend.entrypoints.api.v1.endpoints.skb import build_skb_result_response

pytestmark = [pytest.mark.unit]


class TestBuildSkbResultResponse:
    """Формирование ответа по типу результата."""

    def test_pdf_enum_returns_pdf_response(self) -> None:
        """Enum-член ``pdf`` → PDF-ответ с вложением.

        Args:
            None.
        """
        response = build_skb_result_response(
            b"%PDF-1.4", {"response_type_str": ResponseTypeChoices.pdf}
        )
        assert response.media_type == "application/pdf"
        assert response.body == b"%PDF-1.4"
        assert "result.pdf" in response.headers["content-disposition"]

    def test_pdf_string_returns_pdf_response(self) -> None:
        """Строка ``"PDF"`` → тот же PDF-ответ.

        Args:
            None.
        """
        response = build_skb_result_response(b"%PDF-1.4", {"response_type_str": "PDF"})
        assert response.media_type == "application/pdf"

    def test_json_enum_passes_result_through(self) -> None:
        """JSON-результат возвращается как есть.

        Args:
            None.
        """
        payload: dict[str, Any] = {"Result": True}
        assert (
            build_skb_result_response(
                payload, {"response_type_str": ResponseTypeChoices.json}
            )
            is payload
        )

    def test_missing_response_type_passes_result_through(self) -> None:
        """Без типа ответа результат не превращается в документ.

        Args:
            None.
        """
        payload: dict[str, Any] = {"Result": True}
        assert build_skb_result_response(payload, {}) is payload
