"""Маскирование секретов в HAR-кассетах.

Защищает записанные HTTP-трейсы от утечки токенов/паролей/API-ключей в
``tests/cassettes/``. Применяется автоматически в :class:`HARRecorder`
через ``mask_secrets=True`` (default).

Маскирование выполняется по двум независимым правилам:

* **Header keys** — case-insensitive matching по списку имён
  (``authorization``, ``cookie``, ``x-api-key`` и т. п.); значение
  заменяется на ``"<masked>"``.
* **Body keys** — поиск ключей в JSON/form-urlencoded payload
  (``password``, ``token``, ``secret`` и т. п.); значение заменяется
  на ``"<masked>"`` рекурсивно по nested-структурам.

Алгоритм идемпотентен: повторный вызов на уже замаскированных данных
не меняет результат.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlencode

__all__ = (
    "MASKED_VALUE",
    "SECRET_BODY_KEYS",
    "SECRET_HEADER_KEYS",
    "mask_request_body",
    "mask_response_headers",
)

# Sentinel-значение, которым заменяются обнаруженные секреты.
MASKED_VALUE: str = "<masked>"

# Header-имена, чьё значение всегда содержит секреты (lower-case).
SECRET_HEADER_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-access-token",
        "x-csrf-token",
        "x-session-token",
        "x-amz-security-token",
    }
)

# Body-ключи, чьё значение традиционно содержит секреты.
SECRET_BODY_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "private_key",
        "client_secret",
        "auth",
        "authentication",
        "credentials",
    }
)


def mask_response_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Возвращает копию словаря headers с замаскированными секретами.

    Сравнение имён ключей идёт case-insensitive (``Authorization`` и
    ``authorization`` обрабатываются одинаково). Не-секретные ключи
    сохраняются без изменений.

    Args:
        headers: исходный словарь HTTP headers; ``None`` трактуется
            как пустой словарь.

    Returns:
        Новый словарь с замаскированными секретами. Исходный словарь
        не мутируется.
    """
    if not headers:
        return {}

    masked: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in SECRET_HEADER_KEYS:
            masked[key] = MASKED_VALUE
        else:
            masked[key] = value
    return masked


def mask_request_body(
    body: str | bytes | None,
    *,
    content_type: str | None = None,
) -> str | None:
    """Возвращает body с замаскированными секретными полями.

    Поддерживает три формата (детектируется по ``content_type`` или по
    первому символу payload):

    * JSON (``application/json`` / payload начинается с ``{`` или ``[``)
      — рекурсивный обход словарей/списков, замена значений по ключам
      из :data:`SECRET_BODY_KEYS`.
    * form-urlencoded (``application/x-www-form-urlencoded``) — парсинг
      через ``urllib.parse.parse_qs``, замена секретных полей,
      ре-кодирование.
    * Прочее — возвращается без изменений (нет надёжного способа найти
      секреты в произвольном тексте).

    Args:
        body: исходный body (str или bytes); ``None`` или пустая
            строка возвращаются как-есть.
        content_type: ``Content-Type`` header заголовок; используется
            для выбора парсера. Если не указан — алгоритм пытается
            определить тип по содержимому.

    Returns:
        Замаскированный body как str (или ``None`` если вход был
        ``None``).
    """
    if body is None:
        return None

    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    if not text:
        return text

    ct = (content_type or "").lower()

    if "application/json" in ct or text.lstrip()[:1] in {"{", "["}:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
        return json.dumps(_mask_json_value(parsed), ensure_ascii=False)

    if "application/x-www-form-urlencoded" in ct or _looks_like_form(text):
        return _mask_form_urlencoded(text)

    return text


def _mask_json_value(value: Any) -> Any:
    """Рекурсивно маскирует секретные ключи в произвольной JSON-структуре."""
    if isinstance(value, dict):
        return {
            k: (MASKED_VALUE if k.lower() in SECRET_BODY_KEYS else _mask_json_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_json_value(item) for item in value]
    return value


def _mask_form_urlencoded(text: str) -> str:
    """Маскирует секретные поля в form-urlencoded payload."""
    parsed = parse_qs(text, keep_blank_values=True)
    masked_items: list[tuple[str, str]] = []
    for key, values in parsed.items():
        if key.lower() in SECRET_BODY_KEYS:
            masked_items.extend((key, MASKED_VALUE) for _ in values)
        else:
            masked_items.extend((key, v) for v in values)
    return urlencode(masked_items)


def _looks_like_form(text: str) -> bool:
    """Эвристика: похож ли текст на form-urlencoded payload."""
    if "=" not in text:
        return False
    # Один key=value или несколько через &.
    chunks = text.split("&")
    return all("=" in chunk for chunk in chunks)
