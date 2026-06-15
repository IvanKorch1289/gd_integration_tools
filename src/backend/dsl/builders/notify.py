"""Notify / Shell / Email / SSH / IMAP миксин для RouteBuilder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

from src.backend.dsl.engine.exchange import Exchange


class NotifyMixin:
    """Поведенческий миксин notify / shell / email / ssh.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

    def notify(
        self,
        channel: str = "email",
        *,
        template_key: str = "default",
        recipient: str | None = None,
        priority: str = "tx",
        locale: str = "ru",
        context_property: str | None = None,
        result_property: str = "notify_result",
    ) -> RouteBuilder:
        """Отправка уведомления через NotificationGateway (Wave 8.3).

        Args:
            channel: ``email|sms|slack|teams|telegram|webhook|express``.
            template_key: Имя шаблона в TemplateRegistry.
            recipient: Получатель. Если None — берётся из ``body['recipient']``.
            priority: ``tx`` или ``marketing``.
            locale: Локаль шаблона.
            context_property: Имя property с контекстом для рендера.
            result_property: Имя property для ``SendResult``.
        """
        from src.backend.dsl.engine.processors.notify import NotifyProcessor

        return self._add(  # type: ignore[attr-defined]
            NotifyProcessor(
                channel=channel,
                template_key=template_key,
                recipient=recipient,
                priority=priority,
                locale=locale,
                context_property=context_property,
                result_property=result_property,
            )
        )

    def notify_apprise(
        self,
        channel: str,
        title: str,
        body: str,
        *,
        body_format: str = "text",
        result_property: str = "notify_apprise_result",
    ) -> RouteBuilder:
        """Отправка уведомления через Apprise (S3 K3 W1, 100+ backends).

        Делегирует в :class:`AppriseNotifyProcessor`, который использует
        :class:`~src.backend.services.notifications.AppriseNotificationService`.

        Требует ``feature_flags.notification_dsl_enabled = True`` и
        зарегистрированного канала через
        :meth:`~AppriseNotificationService.register_channel`.

        Args:
            channel: Имя зарегистрированного Apprise-канала (e.g. ``"slack"``).
            title: Заголовок уведомления.
            body: Тело уведомления.
            body_format: Формат тела: ``text`` | ``html`` | ``markdown``.
            result_property: Имя property для результата (``True``/``False``).
        """
        from src.backend.dsl.engine.processors.notify.apprise_notify import (
            AppriseNotifyProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            AppriseNotifyProcessor(
                channel=channel,
                title=title,
                body=body,
                body_format=body_format,
                result_property=result_property,
            )
        )

    def notify_multi(
        self,
        channels: list[str],
        title: str,
        body: str,
        *,
        body_format: str = "text",
        result_property: str = "notify_multi_result",
    ) -> RouteBuilder:
        """Отправка уведомления в несколько Apprise-каналов одновременно (S3 K3 W1).

        Использует :meth:`~AppriseNotificationService.notify_multi` для
        параллельной доставки. Результат — словарь ``{channel: bool}``
        с итогом для каждого канала.

        Args:
            channels: Список имён зарегистрированных каналов.
            title: Заголовок уведомления.
            body: Тело уведомления.
            body_format: Формат тела: ``text`` | ``html`` | ``markdown``.
            result_property: Имя property для словаря результатов.
        """
        from src.backend.dsl.engine.processors.base import CallableProcessor

        async def _send_multi(exch: Exchange[Any], ctx: object) -> None:
            from src.backend.services.notifications.apprise_service import (
                get_notification_service,
            )

            svc = get_notification_service()
            results = await svc.notify_multi(
                channels=channels, title=title, body=body, body_format=body_format
            )
            exch.set_property(result_property, results)

        return self._add(  # type: ignore[attr-defined]
            CallableProcessor(_send_multi, name=f"notify_multi:{','.join(channels)}")
        )

    def shell(
        self,
        command: str,
        *,
        args: list[str] | None = None,
        allowed_commands: list[str] | None = None,
    ) -> RouteBuilder:
        """Shell-команда с whitelist и timeout."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "ShellExecProcessor",
            command=command,
            args=args,
            allowed_commands=allowed_commands,
        )

    def email(self, to: str, subject: str, body_template: str) -> RouteBuilder:
        """Compose + send email через SMTP."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "EmailComposeProcessor",
            to=to,
            subject=subject,
            body_template=body_template,
        )

    @classmethod
    def from_imap(
        cls,
        route_id: str,
        host: str,
        port: int,
        user: str,
        password: str,
        *,
        folder: str = "INBOX",
        subject_filter: str | None = None,
        from_filter: str | None = None,
        **kwargs: Any,
    ) -> RouteBuilder:
        """Фабричный метод: маршрут с источником IMAP IDLE (K3 W5).

        Создаёт :class:`RouteBuilder` с source-описанием IMAP и добавляет
        :class:`~src.backend.dsl.engine.processors.email_trigger.EmailTriggerProcessor`
        как первый шаг фильтрации писем.

        Требует ``feature_flags.email_imap_source = True`` и установки
        ``aioimaplib`` в окружении.

        Args:
            route_id: Уникальный ID маршрута.
            host: IMAP-хост (e.g. ``"imap.gmail.com"``).
            port: IMAP-порт (993 — IMAPS).
            user: Логин пользователя.
            password: Пароль (dev-only; prod — через Vault).
            folder: IMAP-папка для мониторинга (default ``"INBOX"``).
            subject_filter: Substring-фильтр по теме. ``None`` — без фильтра.
            from_filter: Substring-фильтр по отправителю. ``None`` — без фильтра.
            **kwargs: Дополнительные параметры (``description``, ``use_ssl``, и т.д.).

        Returns:
            :class:`RouteBuilder` с предустановленным source и email-фильтром.

        Example::

            route = (
                RouteBuilder.from_imap(
                    "invoice_processing",
                    host="imap.corp.local",
                    port=993,
                    user="robot@corp.local",
                    password="DEV_PASSWORD_PLACEHOLDER",  # dev-only; prod — через Vault
                    folder="INVOICES",
                    subject_filter="INVOICE",
                    from_filter="billing@acme.com",
                )
                .dispatch_action("invoices.process")
                .build()
            )
        """
        from src.backend.dsl.engine.processors.email_trigger import (
            EmailTriggerProcessor,
        )

        description = kwargs.pop("description", None)
        source_tag = f"imap:{host}:{port}/{folder}"
        builder = cls(
            route_id=route_id,
            source=source_tag,
            description=description,
            **{k: v for k, v in kwargs.items() if k in ("_feature_flag",)},
        )
        builder._add(  # type: ignore[attr-defined]
            EmailTriggerProcessor(
                subject_pattern=subject_filter, from_filter=from_filter
            )
        )
        return builder  # type: ignore[return-value]

    def ssh_exec(
        self,
        host: str,
        command: str,
        *,
        username: str | None = None,
        password_from: str = "none",  # noqa: S107  # config field name, not a password
        key_file: str | None = None,
        timeout: float = 30.0,
        result_property: str = "ssh_result",
        continue_on_error: bool = False,
    ) -> RouteBuilder:
        """Выполняет remote-команду через SSH (asyncssh).

        Wave: ``[wave:s35/gap-int-2-ssh-processor]``. Использует
        :class:`SshCommandProcessor` для выполнения команд на удалённых
        SSH-серверах из DSL-маршрутов.

        Args:
            host: Адрес SSH-сервера.
            command: Команда для выполнения.
            username: Имя пользователя для SSH (None — используется
                системный username).
            password_from: Источник пароля: ``"body"``, ``"properties"``
                или ``"none"`` (для key-based auth).
            key_file: Путь к private key-файлу для key-based auth.
            timeout: Таймаут выполнения команды в секундах (default 30.0).
            result_property: Имя property для записи результата
                (``{stdout, stderr, exit_code}``).
            continue_on_error: Если True, не бросает исключение при
                ненулевом exit_code.

        Returns:
            Тот же :class:`RouteBuilder` для продолжения fluent-chain.

        Example::

            route = (
                RouteBuilder.from_("remote_exec", source="timer:interval=60")
                .ssh_exec(
                    "192.168.1.10",
                    "ls -la /data",
                    username="robot",
                    key_file="/secrets/id_rsa",
                )
                .build()
            )
        """
        from src.backend.dsl.engine.processors.ssh_command import SshCommandProcessor

        return self._add(  # type: ignore[attr-defined]
            SshCommandProcessor(
                host=host,
                command=command,
                username=username,
                password_from=password_from,
                key_file=key_file,
                timeout=timeout,
                result_property=result_property,
                continue_on_error=continue_on_error,
            )
        )

    def notify_cascade(
        self,
        *,
        adapters: list[Any] | None = None,
        adapter_names: list[str] | None = None,
        recipient_path: str = "body.recipient",
        subject: str = "",
        body_path: str = "body",
    ) -> RouteBuilder:
        """Fire-and-forget cascade notification with fallback channels.

        Args:
            adapters: List of NotificationAdapter instances.
            adapter_names: DI-registered adapter names (alternative to adapters).
            recipient_path: dotted-path to recipient identifier.
            subject: Notification subject.
            body_path: dotted-path to message body.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.notify_cascade",
            "NotifyCascadeProcessor",
            adapters=adapters or [],
            adapter_names=adapter_names or [],
            recipient_path=recipient_path,
            subject=subject,
            body_path=body_path,
        )
