"""SshCommandProcessor — remote shell execution via SSH (asyncssh).

Sprint 35 GAP-INT-2: добавляет возможность выполнения команд на удалённых
SSH-серверах из DSL-маршрутов.

Usage::

    route = (
        RouteBuilder.from_("remote_exec", source="timer:interval=60")
        .ssh_exec("192.168.1.10", "ls -la /data", username="robot", key_file="/secrets/id_rsa")
        .build()
    )
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.registry import processor

__all__ = ("SshCommandProcessor",)


@processor(
    "ssh_exec",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "host": {"type": "string"},
            "command": {"type": "string"},
            "username": {"type": ["string", "null"]},
            "password_from": {"type": "string", "enum": ["body", "properties", "none"]},
            "key_file": {"type": ["string", "null"]},
            "timeout": {"type": "number"},
            "result_property": {"type": "string"},
            "continue_on_error": {"type": "boolean"},
        },
        "required": ["host", "command"],
    },
    meta={"tier": 2, "category": "sink"},
)
class SshCommandProcessor(BaseProcessor):
    """Выполняет remote-команду через SSH (asyncssh).

    Args:
        host: Адрес SSH-сервера.
        command: Команда для выполнения.
        username: Имя пользователя для SSH (None — используется системный username).
        password_from: Источник пароля: ``"body"``, ``"properties"`` или ``"none"``
            (для key-based auth). При ``"body"``/``"properties"`` пароль читается
            из указанного источника под ключом ``"password"``.
        key_file: Путь к private key-файлу (для key-based auth).
            Поддерживается ``~``expand и relative paths.
        timeout: Таймаут выполнения команды в секундах (default 30.0).
        result_property: Имя property для записи результата
            (``{stdout, stderr, exit_code}``).
        continue_on_error: Если True, не бросает исключение при ненулевом
            exit_code, а записывает результат в exchange.
        name: Имя процессора для трейсов/метрик.
    """

    def __init__(
        self,
        host: str,
        command: str,
        *,
        username: str | None = None,
        password_from: str = "",  # empty = no password (use key auth)
        key_file: str | None = None,
        timeout: float = 30.0,
        result_property: str = "ssh_result",
        continue_on_error: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"ssh:{host}")
        self._host = host
        self._command = command
        self._username = username
        self._password_from = password_from
        self._key_file = key_file
        self._timeout = timeout
        self._result_property = result_property
        self._continue_on_error = continue_on_error

    def _resolve_password(self, exchange: Exchange[Any]) -> str | None:
        """Извлекает пароль из exchange по ``password_from``."""
        if self._password_from == "body":  # noqa: S105
            body = exchange.in_message.body
            if isinstance(body, dict):
                return body.get("password")
            return None
        if self._password_from == "properties":  # noqa: S105
            return exchange.properties.get("password")
        return None  # "none" — key auth или без пароля

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import asyncssh

        password = self._resolve_password(exchange)

        connect_kwargs: dict[str, Any] = {
            "username": self._username,
            "timeout": self._timeout,
        }

        if self._key_file:
            connect_kwargs["client_keys"] = [self._key_file]
        elif password:
            connect_kwargs["password"] = password

        try:
            async with asyncssh.connect(self._host, **connect_kwargs) as conn:
                result = await conn.run(self._command, timeout=self._timeout)
                stdout = result.stdout if result.stdout else ""
                stderr = result.stderr if result.stderr else ""
                exit_code = result.exit_code

                result_data = {
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                }

                exchange.set_property(self._result_property, result_data)

                if exit_code != 0 and not self._continue_on_error:
                    exchange.fail(
                        f"ssh_exec: command exited with code {exit_code}: {stderr or stdout}"
                    )
        except asyncssh.ProcessError as exc:
            if self._continue_on_error:
                exchange.set_property(
                    self._result_property,
                    {
                        "stdout": exc.stdout or "",
                        "stderr": exc.stderr or "",
                        "exit_code": exc.exit_code,
                    },
                )
            else:
                exchange.fail(f"ssh_exec process error: {exc}")

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "host": self._host,
            "command": self._command,
            "timeout": self._timeout,
            "result_property": self._result_property,
            "continue_on_error": self._continue_on_error,
        }
        if self._username is not None:
            spec["username"] = self._username
        if self._password_from:  # non-empty = password is set
            spec["password_from"] = self._password_from
        if self._key_file is not None:
            spec["key_file"] = self._key_file
        return {"ssh_exec": spec}
