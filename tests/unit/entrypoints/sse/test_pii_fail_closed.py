"""Регресс-тесты fail-closed режима PII-редирекции в SSE (волна 36).

Локализация волны 36: в ``sse/handler.py`` при сбое PII-редирекции chunks
прокидывались **без редактирования** (fail-open), а в лог-сообщении
указывалось «Set FEATURE_PII_STREAMING_FAIL_CLOSED=true» — такого флага в
реестре **не существовало**, escape-hatch молча ничего не делал.

Тесты закрывают обе стороны:
* флаг реально существует и читается (default OFF, включается env-переменной);
* при флаге ON сбой редирекции обрывает поток (неотредактированные данные не
  уходят клиенту);
* при флаге OFF сохраняется прежнее best-effort-поведение.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.entrypoints.sse import handler


async def _receive_disconnect() -> dict[str, Any]:
    """Receive-канал, сразу сообщающий о разрыве соединения."""
    return {"type": "http.disconnect"}


@pytest.mark.unit
class TestPiiStreamingFailClosedFlag:
    """Флаг ``FEATURE_PII_STREAMING_FAIL_CLOSED`` существует и читается."""

    def test_flag_exists_with_safe_default(self) -> None:
        """Флаг объявлен в реестре и по умолчанию выключен (прежнее поведение)."""
        from src.backend.core.config.features import feature_flags

        assert hasattr(feature_flags, "pii_streaming_fail_closed")
        assert feature_flags.pii_streaming_fail_closed is False

    def test_flag_reads_runtime_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Значение флага доходит до обработчика через feature-flag service."""
        from src.backend.core.feature_flags import (
            FeatureFlagService,
            get_feature_flag_service,
        )

        assert get_feature_flag_service() is not None
        # Сервис объявлен со ``__slots__ = ()`` → подменяем метод класса.
        monkeypatch.setattr(
            FeatureFlagService,
            "is_enabled",
            lambda self, flag_key, **_kwargs: flag_key == "pii_streaming_fail_closed",
        )

        assert handler._pii_streaming_fail_closed() is True

    def test_flag_off_by_default(self) -> None:
        """Без override флаг выключен — best-effort остаётся поведением по умолчанию."""
        assert handler._pii_streaming_fail_closed() is False


@pytest.mark.unit
class TestSsePiiFailureModes:
    """Поведение SSE-потока при сбое PII-редирекции."""

    @staticmethod
    def _request() -> Any:
        """Минимальный request-объект для SSE-генератора."""
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/events/stream",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
            "http_version": "1.1",
        }
        request = Request(scope, receive=_receive_disconnect)
        return request

    @pytest.mark.asyncio
    async def test_fail_closed_aborts_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При флаге ON сбой редирекции обрывает поток (fail-closed)."""
        from src.backend.services.security import pii_streaming_facade

        async def _boom(*_args: Any, **_kwargs: Any):
            raise RuntimeError("redaction pipeline down")
            yield ""  # pragma: no cover — генератор

        monkeypatch.setattr(pii_streaming_facade, "stream_filter", _boom)
        monkeypatch.setattr(handler, "_pii_streaming_fail_closed", lambda: True)

        response = await handler.sse_stream(self._request())
        generator = response.body_iterator

        with pytest.raises(RuntimeError, match="redaction pipeline down"):
            async for _chunk in generator:
                pass

    @pytest.mark.asyncio
    async def test_best_effort_passes_raw_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При флаге OFF сохраняется прежнее поведение: поток идёт без падения."""
        from src.backend.services.security import pii_streaming_facade

        async def _boom(*_args: Any, **_kwargs: Any):
            raise RuntimeError("redaction pipeline down")
            yield ""  # pragma: no cover — генератор

        monkeypatch.setattr(pii_streaming_facade, "stream_filter", _boom)
        monkeypatch.setattr(handler, "_pii_streaming_fail_closed", lambda: False)

        response = await handler.sse_stream(self._request())
        generator = response.body_iterator

        # Поток не падает: ошибка редикции уходит в warning, а не в исключение.
        chunks: list[Any] = []
        async for chunk in generator:
            chunks.append(chunk)
            if len(chunks) >= 1:
                break
        await generator.aclose()
