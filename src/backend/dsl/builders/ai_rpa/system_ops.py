"""AI / RPA / Banking-AI миксин для RouteBuilder.

Группа: call_llm / call_llm_with_fallback / cache / cache_write /
guardrails / semantic_route / mcp_tool / agent_graph / rag_search /
compose_prompt / parse_llm_output / token_budget / sanitize_pii /
restore_pii / get_feedback_examples / publish_event / load_memory /
save_memory; banking AI (kyc_aml_verify / antifraud_score /
credit_scoring_rag / customer_chatbot / appeal_ai / tx_categorize /
findoc_ocr_llm); RPA (navigate / click / fill_form / extract /
screenshot / run_scenario / citrix / terminal_3270 / appium_mobile /
email_driven / keystroke_replay / scrape / paginate / api_proxy).

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class SystemOpsMixin:
    """system-level operations (shell / email / citrix / terminal / mobile / keystroke replay) для ``RouteBuilder``. S52 W1 extraction."""

    __slots__ = ()

    # --- system operations (shell, email, citrix, terminal, mobile, keystroke replay) ---

    def shell(
        self,
        command: str,
        *,
        args: list[str] | None = None,
        allowed_commands: list[str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> RouteBuilder:
        """Выполнить shell-команду.

        command: имя команды (не full path).
        allowed_commands: whitelist допустимых команд (security).
        timeout_seconds: лимит времени выполнения.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "ShellExecProcessor",
            command=command,
            args=args,
            allowed_commands=allowed_commands,
            timeout_seconds=timeout_seconds,
        )

    def email(self, to: str, subject: str, body_template: str) -> RouteBuilder:
        """Compose + отправка email через SMTP.

        Body: dict с переменными для template или str.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "EmailComposeProcessor",
            to=to,
            subject=subject,
            body_template=body_template,
        )

    def citrix(self, operation: str, session_id: str) -> RouteBuilder:
        """Citrix/RDP-сессия (launch/click/type/screenshot/close)."""
        from src.backend.dsl.engine.processors.rpa_banking import CitrixSessionProcessor

        return self._add(  # type: ignore[attr-defined]
            CitrixSessionProcessor(operation=operation, session_id=session_id)
        )

    def terminal_3270(
        self, host: str, port: int = 23, action: str = "query"
    ) -> RouteBuilder:
        """IBM 3270 терминал-эмулятор (мейнфрейм)."""
        from src.backend.dsl.engine.processors.rpa_banking import (
            TerminalEmulator3270Processor,
        )

        return self._add(  # type: ignore[attr-defined]
            TerminalEmulator3270Processor(host=host, port=port, action=action)
        )

    def appium_mobile(
        self, platform: str, app_package: str, operation: str
    ) -> RouteBuilder:
        """Appium автоматизация мобильных приложений (android/ios)."""
        from src.backend.dsl.engine.processors.rpa_banking import AppiumMobileProcessor

        return self._add(  # type: ignore[attr-defined]
            AppiumMobileProcessor(
                platform=platform, app_package=app_package, operation=operation
            )
        )

    def email_driven(
        self,
        mailbox: str = "INBOX",
        subject_filter: str | None = None,
        extract: str = "body_table",
    ) -> RouteBuilder:
        """IMAP → structured data pipeline."""
        from src.backend.dsl.engine.processors.rpa_banking import EmailDrivenProcessor

        return self._add(  # type: ignore[attr-defined]
            EmailDrivenProcessor(
                mailbox=mailbox, subject_filter=subject_filter, extract=extract
            )
        )

    def keystroke_replay(self, script_name: str) -> RouteBuilder:
        """Воспроизведение записанного сценария клавиатуры/мыши."""
        from src.backend.dsl.engine.processors.rpa_banking import (
            KeystrokeReplayProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            KeystrokeReplayProcessor(script_name=script_name)
        )
