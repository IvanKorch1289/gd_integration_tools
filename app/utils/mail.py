from typing import Any, Dict, List, Optional

import aiosmtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from app.config.settings import MailSettings, settings
from app.utils.utils import singleton


__all__ = ("mail_service",)


@singleton
class MailService:
    """Сервис для работы с электронной почтой."""

    def __init__(self, settings: MailSettings):
        self.settings = settings

    async def check_smtp_connection(self) -> bool:
        """Проверяет доступность SMTP-сервера.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            Exception: Если подключение не удалось.
        """
        try:
            async with aiosmtplib.SMTP(
                hostname=self.settings.mail_host,
                port=self.settings.mail_port,
                use_tls=self.settings.mail_use_tls,
            ) as smtp:
                if self.settings.mail_username and self.settings.mail_password:
                    await smtp.login(
                        self.settings.mail_username, self.settings.mail_password
                    )
            return True
        except Exception as exc:
            raise Exception(f"Ошибка при подключении к SMTP-серверу: {exc}")

    async def send_email(
        self,
        to_emails: List[str],
        subject: str,
        message: str,
        html_message: Optional[str] = None,
    ):
        """Асинхронно отправляет электронное письмо.

        Args:
            to_emails (List[str]): Список адресов получателей.
            subject (str): Тема письма.
            message (str): Текстовое содержимое письма.
            html_message (Optional[str]): HTML-содержимое письма (опционально).

        Raises:
            Exception: Если отправка письма не удалась.
        """
        # Создаем MIME-сообщение
        if html_message:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(message, "plain", "utf-8"))
            msg.attach(MIMEText(html_message, "html", "utf-8"))
        else:
            msg = MIMEText(message, "plain", "utf-8")

        # Заголовки письма
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = formataddr(
            (str(Header("Отправитель", "utf-8")), self.settings.mail_sender)
        )
        msg["To"] = ", ".join(to_emails)

        # Подключение к SMTP-серверу и отправка
        try:
            async with aiosmtplib.SMTP(
                hostname=self.settings.mail_host,
                port=self.settings.mail_port,
                use_tls=self.settings.mail_use_tls,
            ) as smtp:
                if self.settings.mail_username and self.settings.mail_password:
                    await smtp.login(
                        self.settings.mail_username, self.settings.mail_password
                    )
                await smtp.send_message(msg)
        except Exception as exc:
            raise Exception(f"Ошибка при отправке письма: {exc}")

    async def send_email_from_template(
        self,
        to_emails: List[str],
        subject: str,
        template_name: str,
        template_context: Optional[Dict[str, Any]] = None,
    ):
        """Отправляет письмо, используя шаблон из указанной папки.

        Args:
            to_emails (List[str]): Список адресов получателей.
            subject (str): Тема письма.
            template_name (str): Имя шаблона письма.
            template_context (Optional[Dict[str, Any]]): Контекст для подстановки в шаблон.

        Raises:
            ValueError: Если папка с шаблонами не указана или шаблон не найден.
        """
        if not self.settings.mail_template_folder:
            raise ValueError("Папка с шаблонами не указана в настройках.")

        template_path = self.settings.mail_template_folder / template_name
        if not template_path.exists():
            raise ValueError(f"Шаблон {template_name} не найден.")

        # Чтение шаблона
        with open(template_path, "r", encoding="utf-8") as file:
            template_content = file.read()

        # Подстановка контекста (если требуется)
        if template_context:
            template_content = template_content.format(**template_context)

        # Отправка письма
        await self.send_email(to_emails, subject, template_content)


mail_service = MailService(settings=settings.mail)
