"""Express BotX клиент — интеграция с корпоративным мессенджером Express.

Реализует BotX HTTP API v4 (см. https://hackmd.ccsteam.ru/s/E9MPeOxjP).

Аутентификация: JWT HS256, токен генерируется для каждого запроса.

Payload JWT::
    iss = bot_id (UUID)
    aud = botx_host (FQDN)
    exp = now + 60 секунд
    iat = now
    nbf = now
    jti = uuid4() (уникальный per-request)
    version = 2

Ограничения API:
    Content-Length ≤ 512 МБ
    JSON полей (без файла) ≤ 1 МБ
    Файл ≤ 512 МБ

Асинхронные методы возвращают ``sync_id`` — отслеживать через
``get_event_status()``. Обратный вызов: BotX отправляет результат на
``/notification/callback`` бота.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

__all__ = ("BotConfig", "BotxMessage", "BotxButton", "BotxMention", "ExpressBotClient")

_logger = logging.getLogger("infrastructure.express_bot")


@dataclass(slots=True)
class BotConfig:
    """Конфигурация подключения бота Express.

    Attrs:
        bot_id: UUID бота (iss в JWT).
        secret_key: Секретный ключ бота (для подписи JWT, HS256).
        botx_host: FQDN BotX сервера (aud в JWT, пример: cts.ccsteam.ru).
        base_url: URL BotX API (пример: https://cts.ccsteam.ru).
        timeout: Таймаут HTTP запроса в секундах.
    """

    bot_id: str
    secret_key: str
    botx_host: str
    base_url: str
    timeout: float = 30.0


@dataclass(slots=True)
class BotxButton:
    """Кнопка в Express сообщении (bubble или keyboard).

    Attrs:
        command: Команда, отправляемая боту при нажатии (напр. ``/profile``).
        label: Текст на кнопке.
        data: Данные команды (передаются с командой).
        silent: Отправить команду боту без показа в чате.
        h_size: Горизонтальный размер (1 = стандарт).
        show_alert: Показать всплывающее уведомление при нажатии.
        alert_text: Текст уведомления (None → тело команды).
        font_color: Цвет текста в hex (#RRGGBB).
        background_color: Цвет фона в hex (#RRGGBB).
        align: Выравнивание left|center|right.
    """

    command: str
    label: str
    data: dict[str, Any] = field(default_factory=dict)
    silent: bool = False
    h_size: int = 1
    show_alert: bool = False
    alert_text: str | None = None
    font_color: str | None = None
    background_color: str | None = None
    align: str = "left"

    def to_dict(self) -> dict[str, Any]:
        """Сериализация в формат BotX API."""
        result: dict[str, Any] = {
            "command": self.command,
            "label": self.label,
            "data": self.data,
            "silent": self.silent,
            "h_size": self.h_size,
            "show_alert": self.show_alert,
            "align": self.align,
        }
        if self.alert_text:
            result["alert_text"] = self.alert_text
        if self.font_color:
            result["font_color"] = self.font_color
        if self.background_color:
            result["background_color"] = self.background_color
        return result


@dataclass(slots=True)
class BotxMention:
    """Упоминание в сообщении Express.

    Шаблоны в тексте (body)::
        @{mention:<mention_id>}  → user / all / contact
        @@{mention:<mention_id>} → contact
        ##{mention:<mention_id>} → chat / channel

    Attrs:
        mention_type: user | chat | channel | contact | all.
        mention_id: UUID5 идентификатор упоминания.
        user_huid: HUID пользователя (для type=user/contact).
        name: Имя (для type=user) или название чата (для type=chat/channel).
        group_chat_id: UUID чата (для type=chat/channel).
    """

    mention_type: str
    mention_id: str
    user_huid: str | None = None
    name: str | None = None
    group_chat_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Сериализация в формат BotX API."""
        result: dict[str, Any] = {
            "mention_type": self.mention_type,
            "mention_id": self.mention_id,
        }
        mention_data: dict[str, Any] = {}
        if self.user_huid:
            mention_data["user_huid"] = self.user_huid
        if self.name:
            mention_data["name"] = self.name
        if self.group_chat_id:
            mention_data["group_chat_id"] = self.group_chat_id
        if mention_data:
            result["mention_data"] = mention_data
        return result


@dataclass(slots=True)
class BotxMessage:
    """Исходящее сообщение в чат Express.

    Attrs:
        group_chat_id: UUID чата-получателя.
        body: Текст сообщения (макс. 4096 символов).
        status: ``ok`` (успех) | ``error`` (ошибка обработки команды).
        recipients: Список HUID получателей. None → все участники чата.
        bubble: Inline-кнопки под сообщением (2D массив).
        keyboard: Кнопки клавиатуры (2D массив).
        mentions: Упоминания пользователей, чатов, каналов.
        file: Вложение файла (base64, max 512 МБ).
        metadata: Метаданные команды (передаются при нажатии кнопки).
        silent_response: Скрывать ввод пользователя до ответа бота (только 1-1 чат).
        stealth_mode: Отправить только если в чате включён стелс-режим.
    """

    group_chat_id: str
    body: str
    status: str = "ok"
    recipients: list[str] | None = None
    bubble: list[list[BotxButton]] = field(default_factory=list)
    keyboard: list[list[BotxButton]] = field(default_factory=list)
    mentions: list[BotxMention] = field(default_factory=list)
    file: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    silent_response: bool = False
    stealth_mode: bool = False

    def to_payload(self) -> dict[str, Any]:
        """Сериализация в формат BotX API ``/notifications/direct``."""
        opts: dict[str, Any] = {
            "silent_response": self.silent_response,
            "stealth_mode": self.stealth_mode,
        }
        if self.recipients is not None:
            opts["recipients"] = self.recipients

        result: dict[str, Any] = {
            "group_chat_id": self.group_chat_id,
            "notification": {
                "status": self.status,
                "body": self.body,
                "metadata": self.metadata,
                "bubble": [[btn.to_dict() for btn in row] for row in self.bubble],
                "keyboard": [[btn.to_dict() for btn in row] for row in self.keyboard],
                "mentions": [m.to_dict() for m in self.mentions],
            },
            "opts": opts,
        }
        if self.file:
            result["file"] = self.file
        return result


class ExpressBotClient:
    """HTTP клиент BotX API для Express мессенджера.

    Генерирует JWT HS256 для каждого запроса. Методы возвращают ``sync_id`` —
    UUID для отслеживания асинхронных операций. Callback результаты принимает
    entrypoint ``express/`` (см. Wave 4.2).

    Использование::

        client = ExpressBotClient(BotConfig(
            bot_id="...", secret_key="...",
            botx_host="cts.ccsteam.ru",
            base_url="https://cts.ccsteam.ru",
        ))
        async with client:
            sync_id = await client.send_message(BotxMessage(
                group_chat_id="...",
                body="Привет!",
                bubble=[[BotxButton("/profile", "Профиль")]],
            ))
    """

    def __init__(self, config: BotConfig) -> None:
        self._config = config
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ExpressBotClient:
        self._http = httpx.AsyncClient(
            base_url=self._config.base_url, timeout=self._config.timeout
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
                base_url=self._config.base_url, timeout=self._config.timeout
            )
        return self._http

    def _generate_token(self) -> str:
        """Генерирует JWT HS256 токен для текущего запроса.

        Payload: iss=bot_id, aud=botx_host, exp=now+60s, jti=uuid4(), version=2.
        Каждый запрос использует уникальный jti (JWT ID).
        """
        now = datetime.now(UTC)
        payload = {
            "iss": self._config.bot_id,
            "aud": self._config.botx_host,
            "exp": int((now + timedelta(seconds=60)).timestamp()),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "jti": uuid.uuid4().hex,
            "version": 2,
        }
        return jwt.encode(payload, self._config.secret_key, algorithm="HS256")

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._generate_token()}"}

    async def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        """Низкоуровневый POST с JWT и обработкой ошибок."""
        resp = await self.http.post(path, json=json, headers=self._auth_headers())
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    async def _get(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        resp = await self.http.get(path, params=params, headers=self._auth_headers())
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    async def send_message(self, message: BotxMessage, *, sync: bool = False) -> str:
        """Отправляет сообщение в чат.

        Args:
            message: Параметры сообщения.
            sync: False → ``/api/v4/botx/notifications/direct`` (асинхронно).
                  True  → ``/api/v4/botx/notifications/direct/sync`` (синхронно).

        Returns:
            sync_id — UUID отправленного сообщения.
        """
        path = (
            "/api/v4/botx/notifications/direct/sync"
            if sync
            else "/api/v4/botx/notifications/direct"
        )
        result = await self._post(path, message.to_payload())
        return str(result.get("result", {}).get("sync_id") or result.get("sync_id", ""))

    async def reply(self, source_sync_id: str, reply: BotxMessage) -> str:
        """Отвечает на сообщение (reply-thread).

        Args:
            source_sync_id: UUID сообщения, на которое отвечаем.
            reply: Параметры ответа.

        Returns:
            sync_id ответного сообщения.
        """
        payload = reply.to_payload()
        payload["source_sync_id"] = source_sync_id
        result = await self._post("/api/v3/botx/events/reply_event", payload)
        return str(result.get("result", {}).get("sync_id") or result.get("sync_id", ""))

    async def edit_message(self, sync_id: str, **fields: Any) -> None:
        """Редактирует отправленное сообщение.

        Только поля переданные в ``fields`` будут обновлены.
        Для keyboard/bubble: передать ``[]`` → очистить.

        Args:
            sync_id: UUID редактируемого сообщения.
            **fields: body, keyboard, bubble, mentions, file, status.
        """
        payload: dict[str, Any] = {"sync_id": sync_id, "result": {}}
        for key in ("body", "keyboard", "bubble", "mentions", "status"):
            if key in fields:
                payload["result"][key] = fields[key]
        if "file" in fields:
            payload["file"] = fields["file"]
        await self._post("/api/v3/botx/events/edit_event", payload)

    async def delete_message(self, sync_id: str, group_chat_id: str) -> None:
        """Удаляет сообщение из чата."""
        await self._post(
            "/api/v3/botx/events/delete_event",
            {"sync_id": sync_id, "group_chat_id": group_chat_id},
        )

    async def send_typing(self, group_chat_id: str) -> None:
        """Отправляет индикатор набора текста."""
        await self._post("/api/v3/botx/events/typing", {"group_chat_id": group_chat_id})

    async def stop_typing(self, group_chat_id: str) -> None:
        """Останавливает индикатор набора текста."""
        await self._post(
            "/api/v3/botx/events/stop_typing", {"group_chat_id": group_chat_id}
        )

    async def get_event_status(self, sync_id: str) -> dict[str, Any]:
        """Возвращает статус доставки сообщения.

        Returns:
            ``{group_chat_id, sent_to, read_by [{user_huid, read_at}],
            received_by [{user_huid, received_at}]}``.
        """
        return await self._get(
            "/api/v3/botx/events/event_status", params={"sync_id": sync_id}
        )

    async def send_internal_notification(
        self,
        group_chat_id: str,
        data: dict[str, Any],
        recipients: list[str] | None = None,
    ) -> str:
        """Отправляет внутреннюю бот-нотификацию другим ботам в чате.

        Args:
            group_chat_id: UUID чата.
            data: Пользовательские данные.
            recipients: Список bot HUID. None → всем ботам в чате.

        Returns:
            sync_id.
        """
        payload: dict[str, Any] = {
            "group_chat_id": group_chat_id,
            "data": data,
            "opts": {"recipients": recipients} if recipients else {},
        }
        result = await self._post("/api/v4/botx/notifications/internal", payload)
        return str(result.get("result", {}).get("sync_id") or result.get("sync_id", ""))

    async def upload_file(
        self, file_data: bytes, file_name: str, group_chat_id: str
    ) -> dict[str, Any]:
        """Загружает файл в BotX (multipart).

        Ограничения: файл ≤ 512 МБ. Mimetype по расширению имени.

        Returns:
            ``{file_id, file_url}`` для использования в сообщениях.
        """
        files = {"content": (file_name, file_data)}
        data = {"meta": '{"group_chat_id":"%s"}' % group_chat_id}
        resp = await self.http.post(
            "/api/v3/botx/files/upload",
            files=files,
            data=data,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_chat_info(self, group_chat_id: str) -> dict[str, Any]:
        """Возвращает информацию о чате."""
        return await self._get(
            "/api/v3/botx/chats/info", params={"group_chat_id": group_chat_id}
        )

    async def get_members(self, group_chat_id: str) -> list[dict[str, Any]]:
        """Возвращает список участников чата."""
        result = await self._get(
            "/api/v3/botx/chats/members", params={"group_chat_id": group_chat_id}
        )
        members = result.get("result", result)
        return list(members) if isinstance(members, list) else []

    async def search_user(
        self, *, email: str | None = None, huid: str | None = None
    ) -> dict[str, Any] | None:
        """Ищет пользователя по email или HUID.

        Returns:
            Профиль пользователя или None если не найден.
        """
        if not email and not huid:
            raise ValueError("search_user: укажите email или huid")
        params: dict[str, Any] = {}
        if email:
            params["email"] = email
        if huid:
            params["user_huid"] = huid
        try:
            result = await self._get("/api/v3/botx/users/by_email", params=params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return result.get("result", result)
