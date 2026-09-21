"""Тесты PII streaming async-generator (Sprint 3 W1 К1).

Покрывает три сценария:

* **passthrough** — текст без PII проходит без изменений.
* **chunk-boundary** — email/телефон, разрезанный между двумя
  чанками, всё равно маскируется благодаря slide-window-буферу.
* **single-chunk PII** — partial-PII в одном небольшом чанке
  маскируется на финальном flush (буфер flush'ится при close stream-а).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from src.backend.infrastructure.security.pii_streaming import (
    PiiStreamPolicy,
    stream_filter,
)
from src.backend.infrastructure.security.presidio_sanitizer import (
    PresidioSanitizer,
    SanitizeResult,
)


class _FakeSanitizer(PresidioSanitizer):
    """Тестовый sanitizer: подменяет email на ``<EMAIL>``, телефон на ``<PHONE>``.

    Не запускает Presidio (тяжёлая инициализация); делает простую regex-замену.
    """

    def __init__(self) -> None:
        # Намеренно НЕ зовём super().__init__() — чтобы не падать без
        # Presidio. Атрибуты выставляем вручную.
        self._language = "en"
        self._available = False
        self._analyzer = None

    async def sanitize(
        self, text: str, *, entities: list[str] | None = None
    ) -> SanitizeResult:
        import re

        sanitized = text
        replacements: dict[str, str] = {}

        # Email mock-pattern.
        for match in re.finditer(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
            placeholder = "<EMAIL>"
            sanitized = sanitized.replace(match.group(0), placeholder)
            replacements[placeholder] = match.group(0)

        # Phone mock-pattern (+7 9XX XXX-XX-XX style).
        for match in re.finditer(r"\+?7\d{10}", text):
            placeholder = "<PHONE>"
            sanitized = sanitized.replace(match.group(0), placeholder)
            replacements[placeholder] = match.group(0)

        return SanitizeResult(
            sanitized_text=sanitized,
            replacements=replacements,
            entities_found=list(replacements.keys()),
        )


async def _to_list(it: AsyncIterator[str]) -> list[str]:
    """Сворачивает async-iterator в list (helper для тестов)."""
    out: list[str] = []
    async for chunk in it:
        out.append(chunk)
    return out


async def _source(chunks: list[str]) -> AsyncIterator[str]:
    """Превращает list[str] в async-iterator (helper)."""
    for c in chunks:
        yield c


# ---------------------------------------------------------------------------
# Тест 1: passthrough.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passthrough_for_clean_text() -> None:
    """Текст без PII проходит через фильтр без модификаций."""
    sanitizer = _FakeSanitizer()
    chunks = ["Hello, ", "this is a ", "completely clean response."]

    result = await _to_list(
        stream_filter(
            _source(chunks), policy=PiiStreamPolicy(window_chars=8), sanitizer=sanitizer
        )
    )

    joined = "".join(result)
    assert joined == "".join(chunks)


# ---------------------------------------------------------------------------
# Тест 2: PII разрезан на границе chunk-а.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pii_split_across_chunk_boundary_is_redacted() -> None:
    """Email, разрезанный пополам между чанками, всё равно маскируется.

    Slide-window-буфер откладывает хвост до прихода следующего chunk-а,
    поэтому sanitize видит полный email-токен в одном фрагменте.
    """
    sanitizer = _FakeSanitizer()
    # Email разрезан: "alice@example" + ".com end"
    chunks = ["email is alice@exa", "mple.com end"]

    result = await _to_list(
        stream_filter(
            _source(chunks),
            policy=PiiStreamPolicy(window_chars=64),  # buffer > email length
            sanitizer=sanitizer,
        )
    )

    joined = "".join(result)
    assert "alice@example.com" not in joined, "PII не должен утекать в output"
    assert "<EMAIL>" in joined


# ---------------------------------------------------------------------------
# Тест 3: PII целиком в одном маленьком chunk-е — flush на закрытии stream.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_pii_in_single_chunk_is_redacted_on_flush() -> None:
    """Один короткий chunk со всем PII попадает в output через финальный flush.

    Если входной поток короче window_chars, буфер не флёшится в цикле;
    финальный flush после end-of-stream маскирует PII.
    """
    sanitizer = _FakeSanitizer()
    chunks = ["contact me at bob@example.org thanks"]

    result = await _to_list(
        stream_filter(
            _source(chunks),
            policy=PiiStreamPolicy(window_chars=512),
            sanitizer=sanitizer,
        )
    )

    joined = "".join(result)
    assert "bob@example.org" not in joined
    assert "<EMAIL>" in joined


# ---------------------------------------------------------------------------
# Тест 4: phone маскируется через границу chunk-а (бонус для надёжности).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phone_split_across_chunks_is_redacted() -> None:
    """Российский телефон, разрезанный между чанками, маскируется как ``<PHONE>``."""
    sanitizer = _FakeSanitizer()
    chunks = ["call me at +7905", "1234567 today"]

    result = await _to_list(
        stream_filter(
            _source(chunks),
            policy=PiiStreamPolicy(window_chars=32),
            sanitizer=sanitizer,
        )
    )

    joined = "".join(result)
    assert "+79051234567" not in joined
    assert "<PHONE>" in joined
