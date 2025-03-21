from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List

from aiosmtplib import SMTPException

from app.infra.clients.smtp import SmtpClient, smtp_client
from app.utils.decorators.singleton import singleton


__all__ = (
    "get_mail_service",
    "MailService",
)


@singleton
class MailService:
    """Сервис для работы с электронной почтой, поддерживающий использование шаблонов."""

    def __init__(self, mail_client: SmtpClient):
        """
        Инициализирует сервис для работы с электронной почтой.

        Args:
            mail_client (SmtpClient): Клиент для работы с SMTP-сервером.
        """
        from app.utils.logging_service import smtp_logger

        self.client = mail_client
        self.logger = smtp_logger

    async def send_email(
        self,
        to_emails: List[str],
        subject: str,
        message: str,
        html_message: str | None = None,
    ):
        """
        Асинхронно отправляет электронное письмо.

        Args:
            to_emails (List[str]): Список адресов получателей.
            subject (str): Тема письма.
            message (str): Текстовое содержимое письма.
            html_message (str | None): HTML-содержимое письма.

        Raises:
            ValueError: Если не удалось сформировать сообщение.
            RuntimeError: Если не удалось отправить письмо.
        """
        try:
            msg = self._prepare_message(
                to_emails, subject, message, html_message
            )
            async with self.client.get_connection() as smtp:
                await smtp.send_message(msg)
                self.logger.info(f"Отправлено сообщение: {msg}")
        except SMTPException as exc:
            self.logger.error(
                f"Ошибка при отправке письма: {str(exc)}", exc_info=True
            )
            raise RuntimeError(f"Ошибка при отправке письма: {exc}") from exc

    def _prepare_message(self, to_emails, subject, message, html_message):
        """
        Формирует MIME-сообщение с заголовками и содержимым.

        Args:
            to_emails (List[str]): Список адресов получателей.
            subject (str): Тема письма.
            message (str): Текстовое содержимое письма.
            html_message (str | None): HTML-содержимое письма.

        Returns:
            MIMEMultipart|MIMEText: Сформированное сообщение.
        """
        from email.header import Header
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.utils import formataddr

        if html_message:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(message, "plain", "utf-8"))
            msg.attach(MIMEText(html_message, "html", "utf-8"))
        else:
            msg = MIMEText(message, "plain", "utf-8")

        if not isinstance(to_emails, (list, tuple)):
            to_emails = [to_emails]

        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = formataddr(
            (
                (
                    str(Header(self.client.settings.username, "utf-8"))
                    if self.client.settings.username
                    else "unknown"
                ),
                self.client.settings.sender,
            )
        )
        msg["To"] = ", ".join(to_emails)

        return msg

    async def send_email_from_template(
        self,
        to_emails: List[str],
        subject: str,
        template_name: str,
        template_context: Dict[str, Any] | None = None,
    ):
        """
        Отправляет письмо, используя шаблон.

        Args:
            to_emails (List[str]): Список адресов получателей.
            subject (str): Тема письма.
            template_name (str): Имя файла шаблона.
            template_context (Dict[str, Any] | None): Переменные для шаблона.

        Raises:
            ValueError: Если папка с шаблонами не настроена.
            FileNotFoundError: Если файл шаблона не найден.
            RuntimeError: Если произошла ошибка при обработке шаблона.
        """
        from aiofiles import open

        if not self.client.settings.template_folder:
            raise ValueError("Папка с шаблонами не настроена")

        template_path = self.client.settings.template_folder / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"Шаблон не найден: {template_name}")

        try:
            async with open(template_path, mode="r", encoding="utf-8") as f:
                content = await f.read()

            if template_context:
                content = content.format(**template_context)

            await self.send_email(to_emails, subject, content)
        except Exception as exc:
            raise RuntimeError(
                f"Ошибка при обработке шаблона: {str(exc)}"
            ) from exc


@asynccontextmanager
async def get_mail_service() -> AsyncGenerator[MailService, None]:
    """
    Фабрика для создания экземпляра MailService с изолированными зависимостями.

    Yields:
        MailService: Экземпляр сервиса для работы с электронной почтой.
    """
    mail_service = MailService(mail_client=smtp_client)
    try:
        yield mail_service
    finally:
        # Закрытие соединений клиентов, если требуется
        pass
