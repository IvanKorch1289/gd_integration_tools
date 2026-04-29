"""TelegramSendFileProcessor — отправка файла (документа) в Telegram чат.

Источники файла:
- ``s3_key_from`` — выражение, возвращающее S3-ключ. Файл скачивается
  через ``s3_client.get_object_bytes`` (LocalFS поддерживается тем же
  интерфейсом при ``FS_PROVIDER=local``).
- ``file_data_property`` — exchange-property с готовыми ``bytes``.

Файл отправляется через Telegram Bot API ``sendDocument`` (multipart).
"""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.telegram._common import (
    get_telegram_client,
    resolve_value,
)

__all__ = ("TelegramSendFileProcessor",)

_logger = logging.getLogger("dsl.telegram.send_file")


class TelegramSendFileProcessor(BaseProcessor):
    """Отправляет файл (документ) в Telegram чат.

    Args:
        bot: Имя бота.
        chat_id_from: Выражение извлечения chat_id.
        s3_key_from: Выражение извлечения S3-ключа (опционально).
        file_data_property: Имя exchange-property с готовыми ``bytes``
            (приоритет ниже S3).
        file_name: Статическое имя файла (видимое получателю).
        file_name_from: Выражение извлечения имени файла.
        body: Подпись (caption, ≤ 1024 символов).
        body_from: Выражение извлечения подписи.
        parse_mode: Разметка caption.
        disable_notification: Без звука.
        result_property: Имя property для записи message_id.
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        s3_key_from: str | None = None,
        file_data_property: str | None = None,
        file_name: str | None = None,
        file_name_from: str | None = None,
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
        result_property: str = "telegram_file_message_id",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"telegram_send_file({bot})")
        if not s3_key_from and not file_data_property:
            raise ValueError(
                "TelegramSendFileProcessor: укажите s3_key_from или file_data_property"
            )
        if not file_name and not file_name_from:
            raise ValueError(
                "TelegramSendFileProcessor: укажите file_name или file_name_from"
            )
        self._bot = bot
        self._chat_id_from = chat_id_from
        self._s3_key_from = s3_key_from
        self._file_data_property = file_data_property
        self._file_name = file_name
        self._file_name_from = file_name_from
        self._body = body
        self._body_from = body_from
        self._parse_mode = parse_mode
        self._disable_notification = disable_notification
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Загружает файл в Telegram и отправляет сообщение."""
        chat_id = resolve_value(exchange, self._chat_id_from)
        if not chat_id:
            exchange.fail(
                f"TelegramSendFileProcessor: chat_id отсутствует ({self._chat_id_from!r})"
            )
            return

        file_bytes = await self._load_file_bytes(exchange)
        if file_bytes is None:
            exchange.fail("TelegramSendFileProcessor: не удалось получить данные файла")
            return

        file_name = self._file_name or str(
            resolve_value(exchange, self._file_name_from or "") or ""
        )
        if not file_name:
            exchange.fail("TelegramSendFileProcessor: пустое имя файла")
            return

        caption: str | None = self._body
        if caption is None and self._body_from:
            value = resolve_value(exchange, self._body_from)
            if value is not None:
                caption = str(value)

        try:
            client = get_telegram_client(self._bot)
            async with client:
                message_id = await client.send_document(
                    chat_id=str(chat_id),
                    file_data=file_bytes,
                    file_name=file_name,
                    caption=caption,
                    parse_mode=self._parse_mode,
                    disable_notification=self._disable_notification,
                )
            exchange.set_property(self._result_property, message_id)
            _logger.debug(
                "TelegramSendFile: chat_id=%s file=%s message_id=%s",
                chat_id,
                file_name,
                message_id,
            )
        except Exception as exc:
            _logger.warning("TelegramSendFile: ошибка: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    async def _load_file_bytes(self, exchange: Exchange[Any]) -> bytes | None:
        """Загружает файл по приоритету: S3 → exchange-property."""
        if self._s3_key_from:
            key = resolve_value(exchange, self._s3_key_from)
            if key:
                from src.infrastructure.clients.storage.s3_pool import s3_client

                data = await s3_client.get_object_bytes(str(key))
                if data is not None:
                    return data
                _logger.warning(
                    "TelegramSendFile: S3-ключ %r не найден, fallback на property", key
                )

        if self._file_data_property:
            data = exchange.properties.get(self._file_data_property)
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                return data.encode("utf-8")
        return None

    def to_spec(self) -> dict:
        """YAML-spec."""
        spec: dict = {
            "bot": self._bot,
            "chat_id_from": self._chat_id_from,
            "parse_mode": self._parse_mode,
            "disable_notification": self._disable_notification,
            "result_property": self._result_property,
        }
        if self._s3_key_from:
            spec["s3_key_from"] = self._s3_key_from
        if self._file_data_property:
            spec["file_data_property"] = self._file_data_property
        if self._file_name is not None:
            spec["file_name"] = self._file_name
        if self._file_name_from is not None:
            spec["file_name_from"] = self._file_name_from
        if self._body is not None:
            spec["body"] = self._body
        if self._body_from is not None:
            spec["body_from"] = self._body_from
        return {"telegram_send_file": spec}
