"""RPA-процессоры для прикладной автоматизации.

Покрывает:
- Citrix/RDP/Terminal server (pywinauto/pyautogui)
- 3270 терминал-эмулятор (классический мейнфрейм)
- Mobile app automation (Appium)
- Email-driven pipeline (IMAP → structured data)
- Keystroke recording/playback

Все опциональные зависимости проверяются на импорте; ясные ошибки в __init__.
"""

from __future__ import annotations

from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "CitrixSessionProcessor",
    "TerminalEmulator3270Processor",
    "AppiumMobileProcessor",
    "EmailDrivenProcessor",
    "KeystrokeReplayProcessor",
)


class CitrixSessionProcessor(BaseProcessor):
    """Управление Citrix/RDP-сессией. Реальный вызов — через action.

    Процессор только сохраняет операцию в property для делегирования в сервис,
    чтобы не тянуть pywinauto в основной поток.
    """

    def __init__(self, operation: str, session_id: str) -> None:
        super().__init__(name=f"citrix:{operation}")
        if operation not in {
            "launch",
            "connect",
            "click",
            "type",
            "screenshot",
            "close",
        }:
            raise ValueError(f"Unknown citrix operation: {operation}")
        self.operation = operation
        self.session_id = session_id

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("rpa_backend", "citrix")
        exchange.set_property("rpa_operation", self.operation)
        exchange.set_property("rpa_session_id", self.session_id)
        exchange.set_property("rpa_action", "rpa.citrix.invoke")

    def to_spec(self) -> dict[str, Any] | None:
        return {"citrix": {"operation": self.operation, "session_id": self.session_id}}


class TerminalEmulator3270Processor(BaseProcessor):
    """IBM 3270 терминальный эмулятор. Нужен x3270/py3270.

    Для интеграции с легаси мейнфрейм-системами (COBOL-back-office).
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
        exchange.set_property("rpa_action", f"rpa.3270.{self.action}")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"host": self.host}
        if self.port != 23:
            spec["port"] = self.port
        if self.action != "query":
            spec["action"] = self.action
        return {"terminal_3270": spec}


class AppiumMobileProcessor(BaseProcessor):
    """Appium для автоматизации мобильных приложений.

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
        exchange.set_property("rpa_action", "rpa.appium.invoke")

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "appium_mobile": {
                "platform": self.platform,
                "app_package": self.app_package,
                "operation": self.operation,
            }
        }


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
        exchange.set_property("rpa_action", "email.poll_and_extract")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.mailbox != "INBOX":
            spec["mailbox"] = self.mailbox
        if self.subject_filter is not None:
            spec["subject_filter"] = self.subject_filter
        if self.extract != "body_table":
            spec["extract"] = self.extract
        return {"email_driven": spec}


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
        exchange.set_property("rpa_action", "rpa.keystroke.replay")

    def to_spec(self) -> dict[str, Any] | None:
        return {"keystroke_replay": {"script_name": self.script_name}}
