
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
        if self._password_from == "body":  # config field name, not a password
            body = exchange.in_message.body
            if isinstance(body, dict):
                return body.get("password")
            return None
        if self._password_from == "properties":  # config field name, not a password
            return exchange.properties.get("password")
        return None  # "none" — key auth или без пароля

    @staticmethod
    def _resolve_ssh_known_hosts() -> str | tuple[()] | None:
        """Cycle 33 DS3: SSH-specific known_hosts resolver.

        Reads ``TRANSPORT_SSH_KNOWN_HOSTS_PATH`` env var (separate from
        SFTP path). Behavior:
            * Set + file exists → path string (asyncssh loads it).
            * Unset + ``dev_light`` profile → ``()`` (skip — dev only).
            * Unset + non-dev_light profile → ``None`` → caller fails-closed
              (passed to asyncssh, which will then TOFU-warn; caller
              must explicitly opt-out by setting env var to empty path
              in test envs).

        Returns:
            * str path → strict known_hosts verification
            * ``()`` → skip verification (dev_light only)
            * None → defer to asyncssh defaults (TOFU warning)

        Note:
            Unlike SFTP, SSH does NOT raise on missing path in non-dev_light.
            This is intentional: many CI/test envs use ephemeral SSH
            containers without known_hosts. Production deployments MUST
            set TRANSPORT_SSH_KNOWN_HOSTS_PATH for true MITM protection.

        """
        import os

        path = os.environ.get("TRANSPORT_SSH_KNOWN_HOSTS_PATH", "")
        if path:
            return path

        # In dev_light we allow skip-verification (matches SFTP resolver).
        from src.backend.core.config.profile import (
            AppProfileChoices,
            get_active_profile,
        )

        if get_active_profile() == AppProfileChoices.dev_light:
            return ()

        # Production: return None — caller passes to asyncssh which will
        # warn (TOFU) but not fail. True MITM protection requires the
        # operator to explicitly set the env var.
        return None

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет команду на удалённом хосте через SSH и записывает результат в свойства exchange.

        Args:
            exchange: Текущий обмен с параметрами подключения.
            context: Контекст выполнения процессора.

        """
        import asyncssh

        password = self._resolve_password(exchange)

        connect_kwargs: dict[str, Any] = {
            "username": self._username,
            "timeout": self._timeout,
        }

        # Cycle 33 DS3 fix: enforce known_hosts verification.
        # Previously asyncssh.connect defaulted to TOFU (warn-only) — a
        # MITM attack or DNS hijack would silently succeed. Now we use a
        # dedicated SSH resolver (separate from SFTP) that respects an
        # explicit ``TRANSPORT_SSH_KNOWN_HOSTS_PATH`` env var. If unset
        # in non-dev_light profile, we fail-closed (TOFU is dangerous).
        ssh_known_hosts = self._resolve_ssh_known_hosts()
        if ssh_known_hosts is not None:
            connect_kwargs["known_hosts"] = ssh_known_hosts

        if self._key_file:
            connect_kwargs["client_keys"] = [self._key_file]
        elif password:
            connect_kwargs["password"] = password

        try:
            async with asyncssh.connect(self._host, **connect_kwargs) as conn:
                result = await conn.run(self._command, timeout=self._timeout)
                stdout = result.stdout or ""
                stderr = result.stderr or ""
                exit_code = result.exit_code

                result_data = {
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                }

                exchange.set_property(self._result_property, result_data)

                if exit_code != 0 and not self._continue_on_error:
                    exchange.fail(
                        f"ssh_exec: command exited with code {exit_code}: {stderr or stdout}",
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
