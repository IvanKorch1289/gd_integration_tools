"""Тесты для MailService."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.external_apis.mail import MailService


@pytest.fixture
def mail_service(tmp_path: Path) -> MailService:
    """Фикстура с mock SMTP-клиентом и настроенной папкой шаблонов."""
    mock_client = MagicMock()
    mock_client.settings.template_folder = tmp_path
    return MailService(mail_client=mock_client)


class TestSendEmailFromTemplateValidation:
    """Проверка защиты от Path Traversal (HIGH Fix)."""

    @pytest.mark.asyncio
    async def test_rejects_dotdot_in_template_name(
        self, mail_service: MailService
    ) -> None:
        with pytest.raises(ValueError, match="Недопустимое имя шаблона"):
            await mail_service.send_email_from_template(
                to_emails=["a@example.com"],
                subject="subj",
                template_name="../../etc/passwd",
            )

    @pytest.mark.asyncio
    async def test_rejects_absolute_path(self, mail_service: MailService) -> None:
        with pytest.raises(ValueError, match="Недопустимое имя шаблона"):
            await mail_service.send_email_from_template(
                to_emails=["a@example.com"], subject="subj", template_name="/etc/passwd"
            )

    @pytest.mark.asyncio
    async def test_rejects_backslash(self, mail_service: MailService) -> None:
        with pytest.raises(ValueError, match="Недопустимое имя шаблона"):
            await mail_service.send_email_from_template(
                to_emails=["a@example.com"],
                subject="subj",
                template_name="foo\\bar.txt",
            )

    @pytest.mark.asyncio
    async def test_rejects_dot_name(self, mail_service: MailService) -> None:
        with pytest.raises(ValueError, match="Недопустимое имя шаблона"):
            await mail_service.send_email_from_template(
                to_emails=["a@example.com"], subject="subj", template_name="."
            )

    @pytest.mark.asyncio
    async def test_rejects_dotdot_name(self, mail_service: MailService) -> None:
        with pytest.raises(ValueError, match="Недопустимое имя шаблона"):
            await mail_service.send_email_from_template(
                to_emails=["a@example.com"], subject="subj", template_name=".."
            )

    @pytest.mark.asyncio
    async def test_accepts_simple_name(
        self, mail_service: MailService, tmp_path: Path
    ) -> None:
        template_file = tmp_path / "hello.txt"
        template_file.write_text("Hello")

        with patch.object(
            mail_service, "send_email", new_callable=AsyncMock
        ) as mock_send:
            await mail_service.send_email_from_template(
                to_emails=["a@example.com"], subject="subj", template_name="hello.txt"
            )
            mock_send.assert_awaited_once()
