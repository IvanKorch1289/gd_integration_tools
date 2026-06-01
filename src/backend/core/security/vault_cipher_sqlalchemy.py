"""Async-helpers для интеграции VaultTransitCipher со SQLAlchemy моделями.

**Почему не TypeDecorator?**

SQLAlchemy TypeDecorator вызывает ``process_bind_param()`` / ``process_result_value()``
в sync-режиме. ``VaultTransitCipher.encrypt()`` — async (httpx). Вызов
``asyncio.run(cipher.encrypt(...))`` изнутри уже запущенного event loop FastAPI
даёт ``RuntimeError: asyncio.run() cannot be called from a running event loop``.
Использовать ``run_coroutine_threadsafe`` — это дополнительный thread pool,
оверхед и риск deadlock-а под нагрузкой.

**Выбранный паттерн:** сервис явно вызывает helper до ``session.add()`` и после
``session.get()``. Это даёт контроль над lifecycle-ом и явно показывает
encrypt/decrypt point-ы в коде (код-ревью проще).

Пример использования в сервисе::

    from src.backend.core.security.vault_cipher import VaultTransitCipher
    from src.backend.core.security.vault_cipher_sqlalchemy import (
        encrypt_field,
        decrypt_field,
    )

    cipher = VaultTransitCipher(key_name="orders_response")

    async def save_order(payload: dict) -> Order:
        order = Order(response_data=payload)
        # Зашифровать sensitive-поле перед persist-ом.
        await encrypt_field(order, "response_data", cipher, serializer=json.dumps)
        session.add(order)
        await session.commit()
        return order

    async def load_order(order_id: int) -> Order:
        order = await session.get(Order, order_id)
        await decrypt_field(order, "response_data", cipher, deserializer=json.loads)
        return order

В DB остаётся только ciphertext-строка ``vault:v1:<base64>``. При утечке dump-а
БД злоумышленник получает бесполезные шифротексты.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.backend.core.security.vault_cipher import VaultTransitCipher


__all__ = ("encrypt_field", "decrypt_field", "encrypt_mapping", "decrypt_mapping")


logger = logging.getLogger("security.vault_cipher_sa")


# По умолчанию сериализуем через JSON; bytes/str пропускаем как есть.
def _default_serializer(value: Any) -> bytes | str:
    if isinstance(value, (bytes, str)):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _default_deserializer(raw: bytes) -> Any:
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    try:
        return json.loads(text)
    except TypeError, ValueError:
        return text


async def encrypt_field(
    obj: Any,
    field: str,
    cipher: "VaultTransitCipher",
    *,
    serializer: Callable[[Any], bytes | str] | None = None,
) -> None:
    """Шифрует ``obj.<field>`` через ``cipher``; мутирует объект in-place.

    Если поле уже выглядит как ciphertext (``"vault:"``-префикс) —
    повторное шифрование пропускается (идемпотентность).

    :param obj: ORM-объект (или любой объект с атрибутом ``field``).
    :param field: имя атрибута.
    :param cipher: инстанс ``VaultTransitCipher``.
    :param serializer: функция ``value → bytes|str``. По умолчанию JSON
        для dict/list/прочего; bytes/str остаются как есть.
    """
    serializer = serializer or _default_serializer
    value = getattr(obj, field, None)
    if value is None:
        return
    if isinstance(value, str) and value.startswith("vault:"):
        # уже зашифровано — ничего не делаем (идемпотентно)
        return
    plaintext = serializer(value)
    ciphertext = await cipher.encrypt(plaintext)
    setattr(obj, field, ciphertext)


async def decrypt_field(
    obj: Any,
    field: str,
    cipher: "VaultTransitCipher",
    *,
    deserializer: Callable[[bytes], Any] | None = None,
) -> None:
    """Расшифровывает ``obj.<field>``; мутирует объект in-place.

    Если поле не выглядит как ciphertext (нет ``"vault:"``-префикса) —
    считается, что оно уже plaintext (миграционный fallback), ничего не
    делаем.

    :param obj: ORM-объект.
    :param field: имя атрибута.
    :param cipher: инстанс ``VaultTransitCipher``.
    :param deserializer: функция ``bytes → value``. По умолчанию JSON
        decode с fallback на str.
    """
    deserializer = deserializer or _default_deserializer
    value = getattr(obj, field, None)
    if value is None:
        return
    if not isinstance(value, str) or not value.startswith("vault:"):
        # plaintext (миграция в процессе) — оставляем.
        return
    plaintext = await cipher.decrypt(value)
    setattr(obj, field, deserializer(plaintext))


async def encrypt_mapping(
    mapping: dict[str, Any],
    fields: list[str],
    cipher: "VaultTransitCipher",
    *,
    serializer: Callable[[Any], bytes | str] | None = None,
) -> dict[str, Any]:
    """Шифрует указанные ключи словаря; возвращает НОВЫЙ dict (не мутирует).

    Удобно для payload-ов перед insert-ом через Core SQL (без ORM-объекта).
    """
    serializer = serializer or _default_serializer
    result = dict(mapping)
    for f in fields:
        value = result.get(f)
        if value is None:
            continue
        if isinstance(value, str) and value.startswith("vault:"):
            continue
        result[f] = await cipher.encrypt(serializer(value))
    return result


async def decrypt_mapping(
    mapping: dict[str, Any],
    fields: list[str],
    cipher: "VaultTransitCipher",
    *,
    deserializer: Callable[[bytes], Any] | None = None,
) -> dict[str, Any]:
    """Расшифровывает указанные ключи словаря; возвращает НОВЫЙ dict."""
    deserializer = deserializer or _default_deserializer
    result = dict(mapping)
    for f in fields:
        value = result.get(f)
        if value is None:
            continue
        if not isinstance(value, str) or not value.startswith("vault:"):
            continue
        result[f] = deserializer(await cipher.decrypt(value))
    return result
