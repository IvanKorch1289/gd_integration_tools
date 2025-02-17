from contextlib import asynccontextmanager
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiosmtplib

from app.infra.clients.smtp import SmtpClient, smtp_client
from app.utils.logging_service import smtp_logger


__all__ = (
    "get_mail_service",
    "MailService",
)


class MailService:
    """Email service with template support."""

    def __init__(self, mail_client: SmtpClient):
        self.client = mail_client
        self.logger = smtp_logger

    async def send_email(
        self,
        to_emails: List[str],
        subject: str,
        message: str,
        html_message: Optional[str] = None,
    ):
        """
        Send an email message asynchronously.

        Args:
            to_emails (List[str]): List of recipient email addresses
            subject (str): Email subject line
            message (str): Plain text message content
            html_message (Optional[str]): HTML message content

        Raises:
            ValueError: If message construction fails
            RuntimeError: If email sending fails
        """
        try:
            msg = self._prepare_message(
                to_emails, subject, message, html_message
            )
            async with self.client.get_connection() as smtp:
                await smtp.send_message(msg)
                self.logger.info(f"Sent message: {msg}")
        except aiosmtplib.SMTPException as exc:
            self.logger.error("Failed to send email", exc_info=True)
            raise RuntimeError(f"Failed to send email: {exc}") from exc

    def _prepare_message(self, to_emails, subject, message, html_message):
        """
        Construct MIME message with proper headers and content.

        Args:
            to_emails (List[str]): List of recipient emails
            subject (str): Email subject
            message (str): Plain text content
            html_message (Optional[str]): HTML content

        Returns:
            MIMEMultipart|MIMEText: Constructed email message
        """
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
        template_context: Optional[Dict[str, Any]] = None,
    ):
        """
        Send email using a template file.

        Args:
            to_emails (List[str]): List of recipient emails
            subject (str): Email subject
            template_name (str): Name of template file
            template_context (Optional[Dict[str, Any]]): Variables for template

        Raises:
            ValueError: If template folder is not configured
            FileNotFoundError: If template file doesn't exist
            RuntimeError: If template processing fails
        """
        if not self.client.settings.template_folder:
            raise ValueError("Template folder not configured")

        template_path = self.client.settings.template_folder / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_name}")

        try:
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()

            if template_context:
                content = content.format(**template_context)

            await self.send_email(to_emails, subject, content)
        except Exception as exc:
            raise RuntimeError(f"Template processing failed: {exc}") from exc


@asynccontextmanager
async def get_mail_service() -> AsyncGenerator[MailService, None]:
    """
    Фабрика для создания MailService с изолированными зависимостями.
    """
    # Инициализируем клиенты здесь, если они требуют контекста
    mail_service = MailService(mail_client=smtp_client)
    try:
        yield mail_service
    finally:
        # Закрытие соединений клиентов, если требуется
        pass
