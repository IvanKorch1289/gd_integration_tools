"""Async-generator wrapper над PII-sanitizer для streaming-сценариев.

Предоставляет :func:`stream_filter`, которая обёртывает любой
``AsyncIterator[str]`` (SSE/WS/LLM streaming response) и возвращает
такой же поток с маскированными PII-токенами.

Архитектурное обоснование «slide window 4 KB»:

    Текстовые SSE-чанки приходят произвольной длины (например, токены
    LLM по одному символу либо whole-chunk JSON по 256 символов).
    Если граница чанка попадает внутрь email-адреса или номера
    телефона — regex (`AIDataSanitizer`) и NER (Presidio) пропустят
    PII, потому что в одиночном чанке его не видно.

    Решение — буферный slide-window 4 KB. Каждый incoming chunk
    добавляется к буферу; sanitize применяется к
    ``buffer[:-EDGE_TAIL_BYTES]``, остаток (последние EDGE_TAIL_BYTES
    байт) задерживается до прихода следующего чанка. Размер 4 KB
    выбран как компромисс: достаточно большой для длинных PII-токенов
    (IBAN до 34 символов, URL до 2000 байт), но не настолько,
    чтобы вносить заметную latency.

    На последнем чанке буфер flush'ится целиком — все «висящие» байты
    отдаются в output.

Контракт:
    * Если PII-sanitizer недоступен → passthrough без модификации.
    * Sanitize вызывается на полных Unicode-кодпоинтах (split по
      ``str``, не bytes) — race условий с multibyte-границами нет.
    * Output **не сохраняет** chunk-boundaries оригинала — это
      streaming-фильтр, не tee.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from src.backend.infrastructure.security.presidio_sanitizer import (
    PresidioSanitizer,
    get_presidio_sanitizer,
)

__all__ = ("PiiStreamPolicy", "stream_filter")

# Размер «хвостового» буфера в **Unicode-символах** (≈ байт для ASCII).
# 4 KB подобрано как максимум длины потенциального PII (IBAN, JWT, URL).
_DEFAULT_WINDOW_CHARS: int = 4096


@dataclass(frozen=True, slots=True)
class PiiStreamPolicy:
    """Параметры стримингового sanitize.

    Attributes:
        entities: Опц. whitelist Presidio-entity-типов для маскировки;
            ``None`` = маскировать все распознаваемые.
        language: ISO-код языка для Presidio analyzer'а.
        window_chars: Размер хвостового буфера. Default 4096.
            Уменьшайте только в low-latency сценариях, понимая риск
            split-PII через границу chunk-а.
    """

    entities: tuple[str, ...] | None = None
    language: str = "en"
    window_chars: int = _DEFAULT_WINDOW_CHARS


async def stream_filter(
    source: AsyncIterator[str],
    policy: PiiStreamPolicy | None = None,
    *,
    sanitizer: PresidioSanitizer | None = None,
) -> AsyncIterator[str]:
    """Применяет PII-sanitize ко входному streaming-источнику.

    Args:
        source: Async-iterator текстовых чанков (SSE event.data,
            WS message.text, LLM tokens, etc.).
        policy: Конфигурация маскировки (опц.). Default —
            :class:`PiiStreamPolicy` с window_chars=4096.
        sanitizer: Опц. переопределение sanitizer-а (для тестов).
            По умолчанию — глобальный singleton
            :func:`get_presidio_sanitizer`.

    Yields:
        Текстовые чанки с маскированными PII-токенами. Размер
        выходных чанков **не равен** размеру входных — буфер
        сглаживает границы. Caller, ожидающий ровно те же чанки,
        должен использовать sanitize per-message в обход stream_filter.

    Example:
        >>> async def src():
        ...     yield "hello, my email is "
        ...     yield "alice@example.com end"
        >>> async for chunk in stream_filter(src()):
        ...     print(chunk)

    Notes:
        Если sanitizer выдаёт ошибку — chunk прокидывается без
        изменений (best-effort streaming, чтобы не убить SSE-stream
        из-за временной деградации NER).
    """
    pol = policy or PiiStreamPolicy()
    san = sanitizer or get_presidio_sanitizer(language=pol.language)
    window = max(1, pol.window_chars)

    # Накопительный буфер. Все обработанные prefix-чанки уже отданы.
    buffer = ""

    async for chunk in source:
        if not chunk:
            continue
        buffer += chunk
        # Чтобы не разрезать PII на границе следующего входного chunk-а —
        # обрабатываем только префикс, оставляя хвост ``window`` символов
        # для merge с очередным incoming chunk-ом.
        if len(buffer) <= window:
            # Слишком короткий буфер — ждём следующий chunk.
            continue
        head = buffer[:-window]
        buffer = buffer[-window:]
        masked = await _safe_sanitize(san, head, pol.entities)
        if masked:
            yield masked

    # Финальный flush — остатка буфера хватает чтобы покрыть PII целиком,
    # т.к. источник закончился и больше «дотягиваться» нечего.
    if buffer:
        masked = await _safe_sanitize(san, buffer, pol.entities)
        if masked:
            yield masked


async def _safe_sanitize(
    sanitizer: PresidioSanitizer, text: str, entities: tuple[str, ...] | None
) -> str:
    """Вызывает sanitizer и проглатывает исключения (best-effort).

    Args:
        sanitizer: Активный :class:`PresidioSanitizer`.
        text: Текст для маскировки.
        entities: Whitelist entity-типов или ``None``.

    Returns:
        Маскированный текст; при ошибке sanitizer-а — оригинал
        (caller предпочтёт «протекание» PII над разрывом SSE-stream'а).
    """
    try:
        result = await sanitizer.sanitize(
            text, entities=list(entities) if entities else None
        )
    except Exception:  # noqa: BLE001 — streaming best-effort
        return text
    return result.sanitized_text
