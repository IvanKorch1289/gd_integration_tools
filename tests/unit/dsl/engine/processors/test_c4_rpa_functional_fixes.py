"""C4 (ADR-0369) — функциональные баги RPA-процессоров.

Покрывает три дефекта, найденных в Wave 14 (RPA-ревью 2026-10-28):

1. ``HttpRequestProcessor`` при ``to="body"`` писал payload через
   :meth:`BaseProcessor.set_result` → ``set_property("body", ...)``,
   поэтому ``exchange.in_message.body`` оставался пустым.
2. ``ImageOcrProcessor`` не перехватывал ``pytesseract.TesseractNotFoundError``
   (нет бинарника tesseract) → исключение роняло маршрут вместо
   ``exchange.fail(...)``.
3. ``FilteredDirectoryScanProcessor`` в deadline-ветке писал
   ``set_property("body.files", {...})`` вместо ``body.files = []``.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_exchange(body: Any = None) -> MagicMock:
    """Создать mock-exchange с пустым телом."""
    ex = MagicMock()
    ex.in_message = MagicMock()
    ex.in_message.body = {} if body is None else body
    ex.set_property = MagicMock()
    ex.set_error = MagicMock()
    ex.fail = MagicMock()
    ex.stop = MagicMock()
    return ex


class TestHttpRequestProcessorTarget:
    """``to="body"`` → payload в ``in_message.body`` (не в property)."""

    @pytest.mark.asyncio
    async def test_target_body_writes_payload_into_in_message_body(self) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.httprequestprocessor import (
            HttpRequestProcessor,
        )

        p = HttpRequestProcessor(method="GET", url="https://api.example.com/data")
        ex = _make_exchange()
        p.auth_check = AsyncMock(return_value=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json = MagicMock(return_value={"ok": True})
        mock_resp.text = '{"ok": true}'

        class _MockClient:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *a: Any) -> bool:
                return False

            async def request(self, *a: Any, **kw: Any) -> Any:
                return mock_resp

        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=_MockClient(),
        ):
            await p.process(ex, MagicMock())

        payload = ex.in_message.body
        assert isinstance(payload, dict), f"body должен быть dict, got {type(payload)!r}"
        assert payload["status"] == 200
        assert payload["data"] == {"ok": True}
        # target == "body" → НЕ set_property (иначе payload теряется для маршрута).
        ex.set_property.assert_not_called()

    @pytest.mark.asyncio
    async def test_target_body_field_keeps_nested_key(self) -> None:
        """``to="body.response"`` → ``body["response"]`` (регрессия)."""
        from src.backend.dsl.engine.processors.rpa.operations.httprequestprocessor import (
            HttpRequestProcessor,
        )

        p = HttpRequestProcessor(
            method="GET", url="https://api.example.com/data", to="body.response"
        )
        ex = _make_exchange()
        p.auth_check = AsyncMock(return_value=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {}
        mock_resp.json = MagicMock(return_value={"id": 7})
        mock_resp.text = '{"id": 7}'

        class _MockClient:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *a: Any) -> bool:
                return False

            async def request(self, *a: Any, **kw: Any) -> Any:
                return mock_resp

        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=_MockClient(),
        ):
            await p.process(ex, MagicMock())

        assert ex.in_message.body["response"]["status"] == 201
        assert ex.in_message.body["response"]["data"] == {"id": 7}


class TestImageOcrProcessorTesseractMissing:
    """Отсутствие бинарника tesseract → ``exchange.fail``, не исключение."""

    @pytest.mark.asyncio
    async def test_tesseract_not_found_fails_exchange(self) -> None:
        import pytesseract
        from PIL import Image

        from src.backend.dsl.engine.processors.rpa.operations.imageocrprocessor import (
            ImageOcrProcessor,
        )

        buf = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(buf, format="PNG")

        p = ImageOcrProcessor(lang="eng")
        ex = _make_exchange(body=buf.getvalue())
        p.auth_check = AsyncMock(return_value=True)

        with patch(
            "pytesseract.image_to_string",
            side_effect=pytesseract.TesseractNotFoundError(),
        ):
            await p.process(ex, MagicMock())

        ex.fail.assert_called_once()
        assert "tesseract" in str(ex.fail.call_args[0][0]).lower()

    def test_docstring_mentions_actual_output_keys(self) -> None:
        """Docstring описывает реальные ключи результата: text / lang."""
        from src.backend.dsl.engine.processors.rpa.operations.imageocrprocessor import (
            ImageOcrProcessor,
        )

        doc = ImageOcrProcessor.__doc__ or ""
        assert "text" in doc
        assert "lang" in doc
        assert "confidence" not in doc


class TestFilteredDirectoryScanDeadline:
    """Deadline-ветка → ``body.files = []`` + отдельный property-флаг."""

    @pytest.mark.asyncio
    async def test_deadline_exhausted_writes_empty_list_and_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.core.async_utils.deadline_budget import DeadlineBudget
        from src.backend.core.request_context import (
            RequestContext,
            bind_request_context,
            clear_request_context,
        )
        from src.backend.dsl.engine.processors.rpa.operations.filtereddirectoryscanprocessor import (
            FilteredDirectoryScanProcessor,
        )

        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
        budget = DeadlineBudget(
            deadline_ts=time.monotonic() - 1.0, original_timeout=1.0
        )
        ctx = RequestContext(
            correlation_id="c",
            request_id="r",
            method="GET",
            path="/",
            deadline_budget=budget,
        )

        p = FilteredDirectoryScanProcessor(
            directory=str(tmp_path), pattern="*", to="body.files"
        )
        p.auth_check = AsyncMock(return_value=True)
        ex = _make_exchange()

        token = bind_request_context(ctx)
        try:
            await p.process(ex, MagicMock())
        finally:
            clear_request_context(token)

        assert ex.in_message.body["files"] == []
        # Флаг — отдельный property, а не payload внутри body.files.
        flag_keys = [call.args[0] for call in ex.set_property.call_args_list]
        assert flag_keys, "deadline-флаг должен писаться отдельным property"
        assert not any(str(key).startswith("body.files") for key in flag_keys), (
            f"body.files не должен писаться через set_property: {flag_keys}"
        )


class TestRpaBankingStubsAreDocumented:
    """5 banking-заглушек не удалены, а честно задокументированы (ADR-0369)."""

    STUB_CLASSES = (
        "CitrixSessionProcessor",
        "TerminalEmulator3270Processor",
        "AppiumMobileProcessor",
        "EmailDrivenProcessor",
        "KeystrokeReplayProcessor",
    )

    def test_all_five_stubs_still_exist(self) -> None:
        from src.backend.dsl.engine.processors import rpa_banking

        for name in self.STUB_CLASSES:
            assert hasattr(rpa_banking, name), f"{name} удалён — заглушки не удаляем"

    @pytest.mark.parametrize("name", STUB_CLASSES)
    def test_class_docstring_declares_stub(self, name: str) -> None:
        from src.backend.dsl.engine.processors import rpa_banking

        doc = getattr(rpa_banking, name).__doc__ or ""
        assert "Заглушка" in doc, f"{name}: docstring не называет класс заглушкой"

    def test_module_docstring_names_missing_backends(self) -> None:
        from src.backend.dsl.engine.processors import rpa_banking

        doc = rpa_banking.__doc__ or ""
        assert "Заглушки" in doc
        for backend in ("citrix", "3270", "appium", "pyautogui"):
            assert backend in doc, f"в module docstring нет упоминания {backend}"
