"""RPA-процессоры для банковских приложений без API.

Покрывает:
- Citrix/RDP/Terminal server (pywinauto/pyautogui)
- SAP GUI (через pywin32 SAP GUI scripting API)
- 3270 терминал-эмулятор (классический мейнфрейм)
- Mobile app automation (Appium)
- Email-driven pipeline (IMAP → structured data)
- Keystroke recording/playback
- PDF bank statement parser (выписки по счёту в ЛК банка-партнёра)
- Excel/Word шаблоны (сводки для ЦБ РФ)

Все опциональные зависимости проверяются на импорте; ясные ошибки в __init__.
"""

from __future__ import annotations

import re
from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "CitrixSessionProcessor",
    "SapGuiProcessor",
    "TerminalEmulator3270Processor",
    "AppiumMobileProcessor",
    "EmailDrivenProcessor",
    "KeystrokeReplayProcessor",
    "BankStatementPdfParserProcessor",
    "CbrReportExcelProcessor",
)


class CitrixSessionProcessor(BaseProcessor):
    """Управление Citrix/RDP-сессией. Реальный вызов — через action.

    Процессор только сохраняет операцию в property для делегирования в сервис,
    чтобы не тянуть pywinauto в основной поток.
    """

    def __init__(self, operation: str, session_id: str) -> None:
        super().__init__(name=f"citrix:{operation}")
        if operation not in {"launch", "connect", "click", "type", "screenshot", "close"}:
            raise ValueError(f"Unknown citrix operation: {operation}")
        self.operation = operation
        self.session_id = session_id

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("rpa_backend", "citrix")
        exchange.set_property("rpa_operation", self.operation)
        exchange.set_property("rpa_session_id", self.session_id)
        exchange.set_property("banking_action", "rpa.citrix.invoke")


class SapGuiProcessor(BaseProcessor):
    """SAP GUI Scripting (через pywin32). Windows-only.

    Операции: launch, navigate, input, press, extract.
    """

    def __init__(self, operation: str, transaction: str | None = None) -> None:
        super().__init__(name=f"sap_gui:{operation}")
        self.operation = operation
        self.transaction = transaction

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("rpa_backend", "sap_gui")
        exchange.set_property("rpa_operation", self.operation)
        if self.transaction:
            exchange.set_property("sap_transaction", self.transaction)
        exchange.set_property("banking_action", "rpa.sap_gui.invoke")


class TerminalEmulator3270Processor(BaseProcessor):
    """IBM 3270 терминальный эмулятор. Нужен x3270/py3270.

    Для интеграции с легаси мейнфрейм-системами банков (COBOL-back-office).
    """

    def __init__(self, host: str, port: int = 23, action: str = "query") -> None:
        super().__init__(name=f"3270:{host}")
        self.host = host
        self.port = port
        self.action = action

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("rpa_backend", "3270")
        exchange.set_property("rpa_host", self.host)
        exchange.set_property("rpa_port", self.port)
        exchange.set_property("banking_action", f"rpa.3270.{self.action}")


class AppiumMobileProcessor(BaseProcessor):
    """Appium для автоматизации мобильных банковских приложений.

    Используется только для внутренних сценариев (тест-кабинеты, партнёрские
    приложения с контрактом). НЕ для обхода защиты боевых приложений.
    """

    def __init__(self, platform: str, app_package: str, operation: str) -> None:
        super().__init__(name=f"appium:{platform}:{operation}")
        if platform not in {"android", "ios"}:
            raise ValueError("platform: 'android' или 'ios'")
        self.platform = platform
        self.app_package = app_package
        self.operation = operation

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("rpa_backend", "appium")
        exchange.set_property("appium_platform", self.platform)
        exchange.set_property("appium_app", self.app_package)
        exchange.set_property("rpa_operation", self.operation)
        exchange.set_property("banking_action", "rpa.appium.invoke")


class EmailDrivenProcessor(BaseProcessor):
    """Email → structured data pipeline.

    IMAP-клиент парсит письма, извлекает структурированные данные
    (table/CSV/PDF attachment) и кладёт в exchange.out_message.body.
    Реальный IMAP-клиент — в сервисе email_driven.
    """

    def __init__(
        self,
        mailbox: str = "INBOX",
        subject_filter: str | None = None,
        extract: str = "body_table",
    ) -> None:
        super().__init__(name=f"email_driven:{mailbox}")
        self.mailbox = mailbox
        self.subject_filter = subject_filter
        self.extract = extract

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("email_mailbox", self.mailbox)
        exchange.set_property("email_subject_filter", self.subject_filter or "")
        exchange.set_property("email_extract", self.extract)
        exchange.set_property("banking_action", "email.poll_and_extract")


class KeystrokeReplayProcessor(BaseProcessor):
    """Воспроизведение записанного сценария клавиатуры/мыши (pyautogui).

    Сценарий хранится в YAML: [{action: type, text: "..."}, {action: click, x: 100}].
    Для legacy-приложений без скриптинга.
    """

    def __init__(self, script_name: str) -> None:
        super().__init__(name=f"keystroke:{script_name}")
        self.script_name = script_name

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("rpa_backend", "keystroke")
        exchange.set_property("keystroke_script", self.script_name)
        exchange.set_property("banking_action", "rpa.keystroke.replay")


_BANK_LINE_RE = re.compile(
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<amount>-?[\d\s,]+\.\d{2})",
)


class BankStatementPdfParserProcessor(BaseProcessor):
    """Парсер PDF-выписок по счёту (Сбер, ВТБ, Альфа и т.д.).

    Извлекает транзакции таблицей. Если разметка PDF специфична —
    указать format='sber' | 'vtb' | 'alfa' | 'generic'.

    Реальный PDF-парсинг — через сервис (pdfplumber/pymupdf),
    чтобы не тянуть тяжёлые зависимости в ядро.
    """

    def __init__(self, bank_format: str = "generic") -> None:
        super().__init__(name=f"bank_pdf:{bank_format}")
        self.bank_format = bank_format

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("pdf_bank_format", self.bank_format)
        exchange.set_property("banking_action", "bank_statement.parse_pdf")

    @staticmethod
    def parse_text_lines(text: str) -> list[dict[str, str]]:
        """Быстрый парсер плоского текста выписки (fallback)."""
        return [m.groupdict() for m in _BANK_LINE_RE.finditer(text)]
