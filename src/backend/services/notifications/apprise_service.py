"""Сервис уведомлений через Apprise (multi-channel).

Назначение:
    Обёртка над библиотекой ``apprise`` (100+ backends: Slack, Telegram,
    Discord, Email, SMS и др.) для отправки уведомлений из DSL-маршрутов.

Принципы:
    - default-OFF под ``feature_flags.notification_dsl_enabled``.
    - Lazy-import ``apprise`` — не ломает старт если пакет не установлен.
    - Graceful-деградация при ``ImportError`` (warning в лог, возврат False).
    - Singleton через ``get_notification_service()``.
    - Каналы задаются URL-строками в нотации Apprise (e.g. ``slack://...``).

Использование::

    svc = get_notification_service()
    await svc.register_channel("slack", "slack://token/channel")
    ok = await svc.notify("slack", "Заголовок", "Тело сообщения")
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import Literal

__all__ = ("AppriseNotificationService", "get_notification_service")

_log = get_logger(__name__)

# Глобальный singleton
_instance: AppriseNotificationService | None = None


class AppriseNotificationService:
    """Сервис отправки уведомлений через Apprise (100+ backends).

    Args:
        default_channels: Список каналов по умолчанию (имена, зарегистрированные
            через :meth:`register_channel`). Если не задан — каналы передаются
            явно в каждом вызове.

    Атрибуты:
        _channel_urls: Словарь ``{имя_канала: url_apprise}``.
    """

    def __init__(self, default_channels: list[str] | None = None) -> None:
        """Инициализация сервиса.

        Args:
            default_channels: Имена каналов по умолчанию для :meth:`notify`.
        """
        self._default_channels: list[str] = default_channels or []
        self._channel_urls: dict[str, str] = {}

    async def register_channel(self, channel: str, url: str) -> None:
        """Регистрирует канал уведомлений по имени и Apprise URL.

        Args:
            channel: Логическое имя канала (e.g. ``"slack"``, ``"telegram"``).
            url: Apprise-совместимый URL (e.g. ``slack://token/channel``).
        """
        self._channel_urls[channel] = url
        _log.debug("Канал уведомлений зарегистрирован: %s -> %s", channel, url)

    async def notify(
        self,
        channel: str,
        title: str,
        body: str,
        body_format: Literal["text", "html", "markdown"] = "text",
    ) -> bool:
        """Отправить уведомление в один канал.

        Если ``feature_flags.notification_dsl_enabled`` выключен — возвращает
        ``False`` без ошибки. При отсутствии пакета ``apprise`` — логирует
        предупреждение и возвращает ``False``.

        Args:
            channel: Имя зарегистрированного канала.
            title: Заголовок уведомления.
            body: Тело уведомления.
            body_format: Формат тела (``text`` | ``html`` | ``markdown``).

        Returns:
            ``True`` если уведомление отправлено успешно, ``False`` иначе.
        """
        from src.backend.core.config.features import feature_flags

        if not feature_flags.notification_dsl_enabled:
            _log.debug(
                "notification_dsl_enabled=False, пропускаем notify '%s'", channel
            )
            return False

        try:
            import apprise  # lazy-import
        except ImportError:
            _log.warning(
                "Пакет 'apprise' не установлен. Уведомление '%s' пропущено.", channel
            )
            return False

        url = self._channel_urls.get(channel)
        if not url:
            _log.warning(
                "Канал '%s' не зарегистрирован в AppriseNotificationService.", channel
            )
            return False

        apobj = apprise.Apprise()
        apobj.add(url)

        _format_map = {
            "html": apprise.NotifyFormat.HTML,
            "markdown": apprise.NotifyFormat.MARKDOWN,
            "text": apprise.NotifyFormat.TEXT,
        }
        notify_format = _format_map.get(body_format, apprise.NotifyFormat.TEXT)

        result: bool = await apobj.async_notify(
            title=title, body=body, body_format=notify_format
        )
        if not result:
            _log.warning(
                "Уведомление в канал '%s' не доставлено (Apprise вернул False).",
                channel,
            )
        return result

    async def notify_multi(
        self,
        channels: list[str],
        title: str,
        body: str,
        body_format: Literal["text", "html", "markdown"] = "text",
    ) -> dict[str, bool]:
        """Отправить уведомление в несколько каналов параллельно.

        Args:
            channels: Список имён каналов.
            title: Заголовок уведомления.
            body: Тело уведомления.
            body_format: Формат тела.

        Returns:
            Словарь ``{channel: success}`` с результатом для каждого канала.
        """
        import asyncio

        results = await asyncio.gather(
            *[self.notify(ch, title, body, body_format) for ch in channels],
            return_exceptions=True,
        )
        return {
            ch: (bool(r) if not isinstance(r, Exception) else False)
            for ch, r in zip(channels, results)
        }


def get_notification_service() -> AppriseNotificationService:
    """Возвращает глобальный singleton :class:`AppriseNotificationService`.

    Returns:
        Экземпляр :class:`AppriseNotificationService`.
    """
    global _instance
    if _instance is None:
        _instance = AppriseNotificationService()
    return _instance
