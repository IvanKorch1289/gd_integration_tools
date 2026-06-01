"""ExpressSendFileProcessor — отправка файла в Express чат.

Источники файла:
- ``s3_key_from`` — выражение, возвращающее S3-ключ; файл скачивается через
  ``s3_client.get_object_bytes`` (Wave 2.3 LocalFS — поддерживается тем же
  интерфейсом при ``FS_PROVIDER=local``).
- ``file_data_property`` — exchange-property с готовыми ``bytes`` (например,
  результат предыдущего шага).

Файл загружается в BotX через ``upload_file`` (multipart) и затем
прикрепляется к сообщению через ``send_message`` с заполненным
полем ``file = {file_id, file_url}``.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.express._common import (
    get_express_client,
    log_outgoing_message,
    resolve_value,
)

__all__ = ("ExpressSendFileProcessor",)

_logger = logging.getLogger("dsl.express.send_file")


class ExpressSendFileProcessor(BaseProcessor):
    """Отправляет файл в Express чат.

    Args:
        bot: Имя бота из настроек.
        chat_id_from: Выражение извлечения chat_id.
        s3_key_from: Выражение извлечения S3-ключа (опционально).
        file_data_property: Имя exchange-property с готовыми ``bytes``
            (опционально). Источник 2 — приоритет ниже, чем S3.
        file_name: Статическое имя файла (видимое получателю).
        file_name_from: Выражение извлечения имени файла.
        body: Подпись к файлу (опционально).
        body_from: Выражение извлечения подписи.
        result_property: Имя exchange-property для записи sync_id.
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        s3_key_from: str | None = None,
        file_data_property: str | None = None,
        file_name: str | None = None,
        file_name_from: str | None = None,
        body: str | None = None,
        body_from: str | None = None,
        result_property: str = "express_file_sync_id",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"express_send_file({bot})")
        if not s3_key_from and not file_data_property:
            raise ValueError(
                "ExpressSendFileProcessor: укажите s3_key_from или file_data_property"
            )
        if not file_name and not file_name_from:
            raise ValueError(
                "ExpressSendFileProcessor: укажите file_name или file_name_from"
            )
        self._bot = bot
        self._chat_id_from = chat_id_from
        self._s3_key_from = s3_key_from
        self._file_data_property = file_data_property
        self._file_name = file_name
        self._file_name_from = file_name_from
        self._body = body
        self._body_from = body_from
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Загружает файл в BotX и отправляет сообщение со ссылкой."""
        from src.backend.infrastructure.clients.external.express_bot import BotxMessage

        chat_id = resolve_value(exchange, self._chat_id_from)
        if not chat_id:
            exchange.fail(
                f"ExpressSendFileProcessor: chat_id отсутствует ({self._chat_id_from!r})"
            )
            return

        file_bytes = await self._load_file_bytes(exchange)
        if file_bytes is None:
            exchange.fail("ExpressSendFileProcessor: не удалось получить данные файла")
            return

        file_name = self._file_name or str(
            resolve_value(exchange, self._file_name_from or "") or ""
        )
        if not file_name:
            exchange.fail("ExpressSendFileProcessor: пустое имя файла")
            return

        text = self._body or (
            resolve_value(exchange, self._body_from or "") if self._body_from else ""
        )

        try:
            client = get_express_client(self._bot)
            async with client:
                upload = await client.upload_file(
                    file_data=file_bytes,
                    file_name=file_name,
                    group_chat_id=str(chat_id),
                )
                file_meta = upload.get("result", upload)
                msg = BotxMessage(
                    group_chat_id=str(chat_id),
                    body=str(text or file_name),
                    file=file_meta if isinstance(file_meta, dict) else None,
                )
                sync_id = await client.send_message(msg)
            exchange.set_property(self._result_property, sync_id)
            _logger.debug(
                "ExpressSendFile: chat_id=%s file=%s sync_id=%s",
                chat_id,
                file_name,
                sync_id,
            )
            await log_outgoing_message(
                session_id=str(sync_id) if sync_id else str(chat_id),
                body=str(text or file_name),
                bot_id=self._bot,
                group_chat_id=str(chat_id),
                sync_id=str(sync_id) if sync_id else None,
            )
        except Exception as exc:
            _logger.warning("ExpressSendFile: ошибка: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    async def _load_file_bytes(self, exchange: Exchange[Any]) -> bytes | None:
        """Загружает файл из источника-приоритета: S3 → exchange-property."""
        if self._s3_key_from:
            key = resolve_value(exchange, self._s3_key_from)
            if key:
                from src.backend.infrastructure.clients.storage.s3_pool import s3_client

                data = await s3_client.get_object_bytes(str(key))
                if data is not None:
                    return data
                _logger.warning(
                    "ExpressSendFile: S3-ключ %r не найден, fallback на property", key
                )

        if self._file_data_property:
            data = exchange.properties.get(self._file_data_property)
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                return data.encode("utf-8")
        return None

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации."""
        spec: dict = {
            "bot": self._bot,
            "chat_id_from": self._chat_id_from,
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
        return {"express_send_file": spec}
