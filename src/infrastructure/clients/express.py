"""eXpress BotX client — отправка сообщений, создание чатов, events.

eXpress — корпоративный мессенджер (аналог Teams/Slack для внутреннего контура).
Взаимодействие через BotX microservice (RESTful HTTP API).

Docs:
- pybotx: https://github.com/ExpressApp/pybotx
- BotX API: внутренняя документация eXpress

Архитектура:
    Наше приложение → BotX API → eXpress messenger → пользователь

Для работы:
1. Зарегистрировать бота в eXpress админке → получить bot_id + secret_key
2. BotX URL (обычно https://botx.corp.example.ru)
3. Настроить callback /command (если бот принимает сообщения)
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

__all__ = ("ExpressClient", "get_express_client")

logger = logging.getLogger(__name__)


class ExpressClient:
    """Async клиент для eXpress BotX API.

    Обёртка над pybotx.Bot с упрощённым интерфейсом для сервиса.
    Lazy-init: pybotx загружается при первом вызове.
    """

    def __init__(
        self,
        bot_id: str,
        secret_key: str,
        botx_url: str,
        enabled: bool = True,
    ) -> None:
        self._bot_id = bot_id
        self._secret_key = secret_key
        self._botx_url = botx_url
        self._enabled = enabled
        self._bot: Any = None

    async def _get_bot(self) -> Any:
        """Lazy-init pybotx Bot."""
        if self._bot is not None:
            return self._bot
        try:
            from pybotx import Bot, BotAccountWithSecret
        except ImportError as exc:
            raise RuntimeError(
                "pybotx не установлен. Установите: pip install pybotx"
            ) from exc

        account = BotAccountWithSecret(
            id=UUID(self._bot_id),
            cts_url=self._botx_url,
            secret_key=self._secret_key,
        )
        self._bot = Bot(collectors=[], bot_accounts=[account])
        await self._bot.startup()
        logger.info("eXpress BotX client connected: %s", self._botx_url)
        return self._bot

    async def close(self) -> None:
        if self._bot:
            await self._bot.shutdown()
            self._bot = None

    async def send_message(
        self,
        chat_id: str,
        text: str,
        mentions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Отправляет сообщение в чат eXpress.

        Args:
            chat_id: UUID чата.
            text: Текст сообщения (Markdown поддерживается).
            mentions: Список HUID пользователей для упоминания.

        Returns:
            {"status": "sent", "sync_id": "..."}
        """
        if not self._enabled:
            return {"status": "disabled"}

        try:
            from pybotx import OutgoingMessage

            bot = await self._get_bot()
            message = OutgoingMessage(
                bot_id=UUID(self._bot_id),
                chat_id=UUID(chat_id),
                body=text,
            )
            sync_id = await bot.send_message(message=message)
            return {"status": "sent", "sync_id": str(sync_id), "chat_id": chat_id}
        except Exception as exc:
            logger.error("eXpress send_message failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def send_direct(self, user_huid: str, text: str) -> dict[str, Any]:
        """Отправляет личное сообщение пользователю по HUID."""
        if not self._enabled:
            return {"status": "disabled"}

        try:
            bot = await self._get_bot()
            chat_id = await bot.create_chat(
                bot_id=UUID(self._bot_id),
                name="Direct",
                chat_type="chat",
                huids=[UUID(user_huid)],
            )
            return await self.send_message(str(chat_id), text)
        except Exception as exc:
            logger.error("eXpress send_direct failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def create_chat(
        self,
        name: str,
        members: list[str],
        chat_type: str = "group_chat",
        description: str = "",
    ) -> dict[str, Any]:
        """Создаёт групповой чат.

        Args:
            name: Название чата.
            members: Список HUID участников.
            chat_type: "group_chat" или "channel".
            description: Описание чата.

        Returns:
            {"status": "created", "chat_id": "..."}
        """
        if not self._enabled:
            return {"status": "disabled"}

        try:
            bot = await self._get_bot()
            chat_id = await bot.create_chat(
                bot_id=UUID(self._bot_id),
                name=name,
                chat_type=chat_type,
                huids=[UUID(m) for m in members],
                description=description,
            )
            logger.info("eXpress chat created: %s (%s)", name, chat_id)
            return {"status": "created", "chat_id": str(chat_id), "name": name}
        except Exception as exc:
            logger.error("eXpress create_chat failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def add_users_to_chat(
        self, chat_id: str, user_huids: list[str]
    ) -> dict[str, Any]:
        """Добавляет пользователей в чат."""
        if not self._enabled:
            return {"status": "disabled"}

        try:
            bot = await self._get_bot()
            await bot.add_users_to_chat(
                bot_id=UUID(self._bot_id),
                chat_id=UUID(chat_id),
                huids=[UUID(h) for h in user_huids],
            )
            return {"status": "added", "count": len(user_huids)}
        except Exception as exc:
            logger.error("eXpress add_users failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def send_notification(
        self,
        group_chat_ids: list[str],
        text: str,
    ) -> dict[str, Any]:
        """Broadcast уведомление в несколько чатов одновременно."""
        if not self._enabled:
            return {"status": "disabled"}

        results = []
        for chat_id in group_chat_ids:
            r = await self.send_message(chat_id, text)
            results.append(r)
        sent = sum(1 for r in results if r.get("status") == "sent")
        return {"status": "broadcast", "sent": sent, "total": len(group_chat_ids)}

    async def search_user_by_email(self, email: str) -> dict[str, Any]:
        """Ищет пользователя по email. Возвращает HUID."""
        if not self._enabled:
            return {"status": "disabled"}

        try:
            bot = await self._get_bot()
            user = await bot.search_user_by_email(
                bot_id=UUID(self._bot_id),
                email=email,
            )
            return {
                "huid": str(user.user_huid),
                "name": user.username,
                "email": user.emails[0] if user.emails else "",
            }
        except Exception as exc:
            return {"status": "not_found", "message": str(exc)}

    async def edit_message(
        self, sync_id: str, new_text: str
    ) -> dict[str, Any]:
        """Редактирует ранее отправленное сообщение."""
        if not self._enabled:
            return {"status": "disabled"}

        try:
            from pybotx import EditMessage

            bot = await self._get_bot()
            await bot.edit_message(
                bot_id=UUID(self._bot_id),
                sync_id=UUID(sync_id),
                body=new_text,
            )
            return {"status": "edited", "sync_id": sync_id}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    async def delete_message(self, sync_id: str) -> dict[str, Any]:
        """Удаляет сообщение."""
        if not self._enabled:
            return {"status": "disabled"}

        try:
            bot = await self._get_bot()
            await bot.delete_message(
                bot_id=UUID(self._bot_id),
                sync_id=UUID(sync_id),
            )
            return {"status": "deleted", "sync_id": sync_id}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


_express_client: ExpressClient | None = None


def get_express_client() -> ExpressClient:
    """Возвращает ExpressClient из app.state или lazy-init fallback."""
    global _express_client
    from app.core.di import _get_from_app_state

    instance = _get_from_app_state("express_client")
    if instance is not None:
        return instance

    if _express_client is None:
        from app.core.config.express_settings import express_settings

        _express_client = ExpressClient(
            bot_id=express_settings.bot_id,
            secret_key=express_settings.secret_key,
            botx_url=express_settings.botx_url,
            enabled=express_settings.enabled,
        )
    return _express_client
