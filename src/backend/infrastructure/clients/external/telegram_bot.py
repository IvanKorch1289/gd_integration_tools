"""Telegram Bot API клиент (W15.3).

Реализует Bot API ``https://core.telegram.org/bots/api``.

Аутентификация: токен в URL (``/bot{token}/{method}``). JWT/HMAC не нужны.

Архитектура повторяет :class:`~src.infrastructure.clients.external.express_bot.
ExpressBotClient` — единый bot-channel контракт через
``BaseBotChannelSettings`` (W15.2). Это упрощает миграцию между
мессенджерами и реализацию ``NotificationGateway`` адаптеров.

Ограничения:
    Текст сообщения ≤ 4096 символов.
    caption (sendDocument/Photo) ≤ 1024 символов.
    Файл ≤ 50 МБ через Bot API (50 МБ document, 10 МБ photo).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

__all__ = (
    "TelegramBotClient",
    "TelegramBotConfig",
    "TelegramButton",
    "TelegramMention",
    "TelegramMessage",
)

_logger = logging.getLogger("infrastructure.telegram_bot")

# Допустимые значения parse_mode Telegram.
ParseMode = Literal["HTML", "MarkdownV2", "Markdown", ""]

# Допустимые значения sendChatAction.
ChatAction = Literal[
    "typing",
    "upload_photo",
    "record_video",
    "upload_video",
    "record_voice",
    "upload_voice",
    "upload_document",
    "find_location",
    "record_video_note",
    "upload_video_note",
]


@dataclass(slots=True)
class TelegramBotConfig:
    """Конфигурация подключения бота Telegram.

    Attrs:
        bot_id: Числовой ID бота (часть до ``:`` в токене).
        secret_key: Часть после ``:`` в токене.
        base_url: HTTPS endpoint Bot API (default ``https://api.telegram.org``).
        timeout: Таймаут HTTP запроса в секундах.
    """

    bot_id: str
    secret_key: str
    base_url: str = "https://api.telegram.org"
    timeout: float = 30.0

    @property
    def token(self) -> str:
        """Полный токен ``{bot_id}:{secret_key}`` для подстановки в URL."""
        return f"{self.bot_id}:{self.secret_key}"


@dataclass(slots=True)
class TelegramButton:
    """Inline-кнопка Telegram (InlineKeyboardButton).

    Поддерживает только ОДИН тип действия: либо ``url``, либо
    ``callback_data``, либо ``switch_inline_query``. См. Bot API.

    Attrs:
        text: Текст на кнопке (обязательный).
        url: HTTPS / tg:// ссылка.
        callback_data: Данные, отправляемые в callback при нажатии (≤ 64 байт).
        switch_inline_query: Перевод чата в inline mode с заданным запросом.
        web_app_url: URL Web App (откроется в WebView).
    """

    text: str
    url: str | None = None
    callback_data: str | None = None
    switch_inline_query: str | None = None
    web_app_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Сериализация в формат Bot API InlineKeyboardButton."""
        result: dict[str, Any] = {"text": self.text}
        if self.url:
            result["url"] = self.url
        if self.callback_data is not None:
            result["callback_data"] = self.callback_data
        if self.switch_inline_query is not None:
            result["switch_inline_query"] = self.switch_inline_query
        if self.web_app_url:
            result["web_app"] = {"url": self.web_app_url}
        return result


@dataclass(slots=True)
class TelegramMention:
    """Упоминание пользователя через MarkdownV2 / HTML.

    Telegram не имеет отдельного поля mentions в API: упоминания
    встраиваются прямо в ``text`` через MarkdownV2:
    ``[@username](tg://user?id=12345)``. Объект собирает кусок разметки.

    Attrs:
        user_id: Числовой ID пользователя.
        display_name: Отображаемое имя.
        parse_mode: ``HTML`` или ``MarkdownV2``.
    """

    user_id: int
    display_name: str
    parse_mode: ParseMode = "MarkdownV2"

    def to_inline(self) -> str:
        """Возвращает фрагмент разметки для вставки в текст."""
        if self.parse_mode == "HTML":
            return f'<a href="tg://user?id={self.user_id}">{self.display_name}</a>'
        # MarkdownV2 / Markdown — экранирование квадратных скобок не требуется
        # для display_name (ответственность вызывающего).
        return f"[{self.display_name}](tg://user?id={self.user_id})"


@dataclass(slots=True)
class TelegramMessage:
    """Исходящее сообщение Telegram.

    Attrs:
        chat_id: ID чата (int) или username канала (``@channel``).
        text: Текст сообщения.
        parse_mode: HTML / MarkdownV2 / Markdown / "" (без разметки).
        inline_keyboard: 2D массив inline-кнопок под сообщением.
        reply_keyboard: 2D массив reply-кнопок (как клавиатура).
        reply_to_message_id: ID сообщения, на которое отвечаем.
        disable_notification: Без звука.
        disable_web_page_preview: Не показывать превью ссылки.
        protect_content: Запретить пересылку и сохранение.
    """

    chat_id: str
    text: str
    parse_mode: ParseMode = "HTML"
    inline_keyboard: list[list[TelegramButton]] = field(default_factory=list)
    reply_keyboard: list[list[str]] = field(default_factory=list)
    reply_to_message_id: int | None = None
    disable_notification: bool = False
    disable_web_page_preview: bool = False
    protect_content: bool = False

    def to_payload(self) -> dict[str, Any]:
        """Сериализация в формат ``sendMessage``."""
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": self.text}
        if self.parse_mode:
            payload["parse_mode"] = self.parse_mode
        if self.inline_keyboard:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [btn.to_dict() for btn in row] for row in self.inline_keyboard
                ]
            }
        elif self.reply_keyboard:
            payload["reply_markup"] = {
                "keyboard": [
                    [{"text": label} for label in row] for row in self.reply_keyboard
                ],
                "resize_keyboard": True,
            }
        if self.reply_to_message_id is not None:
            payload["reply_to_message_id"] = self.reply_to_message_id
        if self.disable_notification:
            payload["disable_notification"] = True
        if self.disable_web_page_preview:
            payload["disable_web_page_preview"] = True
        if self.protect_content:
            payload["protect_content"] = True
        return payload


class TelegramBotClient:
    """HTTP клиент Telegram Bot API.

    Использование::

        client = TelegramBotClient(TelegramBotConfig(
            bot_id="12345", secret_key="ABC-DEF...",
        ))
        async with client:
            message_id = await client.send_message(TelegramMessage(
                chat_id="@my_channel",
                text="Привет!",
                inline_keyboard=[[TelegramButton("Открыть", url="https://example.com")]],
            ))
    """

    def __init__(self, config: TelegramBotConfig) -> None:
        self._config = config
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> TelegramBotClient:
        self._http = httpx.AsyncClient(
            base_url=f"{self._config.base_url}/bot{self._config.token}",
            timeout=self._config.timeout,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        """Возвращает активный HTTP клиент или создаёт временный."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=f"{self._config.base_url}/bot{self._config.token}",
                timeout=self._config.timeout,
            )
        return self._http

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Низкоуровневый POST к Bot API.

        Telegram возвращает ``{ok, result}`` или ``{ok: false, description}``.
        В случае ошибки поднимает ``httpx.HTTPStatusError`` с текстом
        ``description`` в message.
        """
        resp = await self.http.post(f"/{method}", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise httpx.HTTPStatusError(
                f"Telegram API {method}: {data.get('description', 'unknown error')}",
                request=resp.request,
                response=resp,
            )
        result = data.get("result")
        return result if isinstance(result, dict) else {"result": result}

    async def send_message(self, message: TelegramMessage) -> int:
        """Отправляет сообщение в чат.

        Args:
            message: Параметры сообщения.

        Returns:
            ``message_id`` отправленного сообщения.
        """
        result = await self._call("sendMessage", message.to_payload())
        return int(result.get("message_id", 0))

    async def reply(self, source_message_id: int, reply: TelegramMessage) -> int:
        """Отвечает на сообщение (Telegram thread reply).

        Args:
            source_message_id: ID сообщения, на которое отвечаем.
            reply: Параметры ответа (chat_id берётся из reply.chat_id).

        Returns:
            ``message_id`` ответного сообщения.
        """
        payload = reply.to_payload()
        payload["reply_to_message_id"] = source_message_id
        result = await self._call("sendMessage", payload)
        return int(result.get("message_id", 0))

    async def edit_message(
        self,
        chat_id: str,
        message_id: int,
        *,
        text: str | None = None,
        parse_mode: ParseMode = "HTML",
        inline_keyboard: list[list[TelegramButton]] | None = None,
    ) -> None:
        """Редактирует отправленное сообщение.

        Args:
            chat_id: ID чата.
            message_id: ID редактируемого сообщения.
            text: Новый текст. Если None — изменяется только разметка.
            parse_mode: HTML / MarkdownV2 / Markdown.
            inline_keyboard: Новые inline-кнопки. ``[]`` → очистить.
        """
        if text is not None:
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if inline_keyboard is not None:
                payload["reply_markup"] = {
                    "inline_keyboard": [
                        [btn.to_dict() for btn in row] for row in inline_keyboard
                    ]
                }
            await self._call("editMessageText", payload)
        elif inline_keyboard is not None:
            await self._call(
                "editMessageReplyMarkup",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": {
                        "inline_keyboard": [
                            [btn.to_dict() for btn in row] for row in inline_keyboard
                        ]
                    },
                },
            )

    async def delete_message(self, chat_id: str, message_id: int) -> None:
        """Удаляет сообщение из чата."""
        await self._call(
            "deleteMessage", {"chat_id": chat_id, "message_id": message_id}
        )

    async def send_chat_action(
        self, chat_id: str, action: ChatAction = "typing"
    ) -> None:
        """Отправляет статус действия (печатает / загружает фото / …)."""
        await self._call("sendChatAction", {"chat_id": chat_id, "action": action})

    async def send_document(
        self,
        chat_id: str,
        file_data: bytes,
        file_name: str,
        *,
        caption: str | None = None,
        parse_mode: ParseMode = "HTML",
        disable_notification: bool = False,
    ) -> int:
        """Отправляет документ (multipart upload).

        Args:
            chat_id: ID чата.
            file_data: Бинарное содержимое файла (≤ 50 МБ).
            file_name: Имя файла с расширением.
            caption: Подпись (≤ 1024 символов).
            parse_mode: Разметка caption.
            disable_notification: Без звука.

        Returns:
            ``message_id`` отправленного сообщения.
        """
        files = {"document": (file_name, file_data)}
        data: dict[str, Any] = {"chat_id": chat_id}
        if caption is not None:
            data["caption"] = caption
            if parse_mode:
                data["parse_mode"] = parse_mode
        if disable_notification:
            data["disable_notification"] = "true"
        resp = await self.http.post("/sendDocument", files=files, data=data)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("ok"):
            raise httpx.HTTPStatusError(
                f"Telegram API sendDocument: {body.get('description', 'unknown error')}",
                request=resp.request,
                response=resp,
            )
        return int(body.get("result", {}).get("message_id", 0))

    async def set_my_commands(
        self, commands: list[dict[str, str]], *, language_code: str | None = None
    ) -> None:
        """Устанавливает список команд бота (для меню в клиенте).

        Args:
            commands: ``[{"command": "start", "description": "Запуск"}]``.
            language_code: BCP 47 (ru / en / …). None → default.
        """
        payload: dict[str, Any] = {"commands": commands}
        if language_code:
            payload["language_code"] = language_code
        await self._call("setMyCommands", payload)

    async def get_me(self) -> dict[str, Any]:
        """Возвращает информацию о боте (для health-check)."""
        return await self._call("getMe", {})
