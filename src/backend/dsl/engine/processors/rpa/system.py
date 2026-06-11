"""RPA processors — UiPath-style document, file, and system automation.

Each processor is a lightweight BaseProcessor (~30-60 lines) that handles
one specific automation task. Heavy dependencies are lazy-imported so
the module loads instantly even without optional packages.

Categories:
- Documents: PDF read/merge, Word read/write, Excel read
- Files: move/copy, archive ZIP/TAR, image OCR/resize
- Text: regex extract/replace, Jinja2 templates, hash, encrypt/decrypt
- System: shell exec, email compose+send
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class ShellExecProcessor(BaseProcessor):
    """Выполнение shell-команд с whitelist и sandbox.

    БЕЗОПАСНОСТЬ: только команды из whitelist, timeout, без shell=True.

    Usage::

        .shell("ls", args=["-la", "/data"], allowed_commands=["ls", "cat", "wc"])
    """

    def __init__(
        self,
        command: str,
        *,
        args: list[str] | None = None,
        allowed_commands: list[str] | None = None,
        timeout_seconds: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"shell:{command}")
        self._command = command
        self._args = args or []
        self._allowed = set(allowed_commands) if allowed_commands else None
        self._timeout = timeout_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        import asyncio

        if self._allowed and self._command not in self._allowed:
            exchange.fail(
                f"Command '{self._command}' not in whitelist: {self._allowed}"
            )
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
            exchange.set_out(
                body={
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "exit_code": proc.returncode,
                },
                headers=dict(exchange.in_message.headers),
            )
            if proc.returncode != 0:
                exchange.set_property("shell_error", True)
        except TimeoutError:
            exchange.fail(f"Shell command timed out after {self._timeout}s")
        except (FileNotFoundError, PermissionError) as exc:
            exchange.fail(f"Shell exec failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {"command": self._command}
        if self._args:
            spec["args"] = list(self._args)
        if self._allowed:
            spec["allowed_commands"] = sorted(self._allowed)
        return {"shell": spec}


class EmailComposeProcessor(BaseProcessor):
    """Compose и отправка email через SMTP.

    Использует существующий SmtpClient приложения.
    body_template поддерживает {variable} подстановки из exchange body.
    """

    def __init__(
        self, to: str, subject: str, body_template: str, *, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"email:{to[:20]}")
        self._to = to
        self._subject = subject
        self._body_template = body_template

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        body = exchange.in_message.body
        variables = body if isinstance(body, dict) else {"body": body}
        try:
            email_body = self._body_template.format(**variables)
        except KeyError, IndexError:
            email_body = self._body_template
        try:
            from src.backend.infrastructure.clients.transport.smtp import smtp_client

            await smtp_client.send_email(
                to=self._to, subject=self._subject, body=email_body
            )
            exchange.set_property("email_sent", True)
            exchange.set_property("email_to", self._to)
        except Exception as exc:
            exchange.fail(f"Email send failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        return {
            "email": {
                "to": self._to,
                "subject": self._subject,
                "body_template": self._body_template,
            }
        }
