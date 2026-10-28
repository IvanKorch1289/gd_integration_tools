"""ADR-0368 — отказоустойчивость RPA-процессоров ``rpa/system.py``.

Покрывает:
* ``ShellExecProcessor`` — таймаут обязан убивать дочерний процесс;
* ``ShellExecProcessor`` — fail-closed без whitelist (решение D2);
* ``EmailReadProcessor`` — socket-timeout для IMAP + внешний wait_for.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.rpa.system import (
    EmailReadProcessor,
    ShellExecProcessor,
)


def _exchange() -> Exchange[Any]:
    return Exchange(in_message=Message(body={}))


@pytest.mark.unit
class TestShellExecFaultTolerance:
    """ShellExecProcessor: kill по таймауту + fail-closed whitelist."""

    async def test_timeout_kills_child_process(self) -> None:
        """По таймауту дочерний процесс обязан быть убит (иначе — зомби)."""
        processor = ShellExecProcessor(
            command="sleep",
            args=["987654"],
            allowed_commands=["sleep"],
            timeout_seconds=0.2,
        )
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[assignment]
        exchange = _exchange()

        created: list[Any] = []
        real_exec = asyncio.create_subprocess_exec

        async def _spy(*args: Any, **kwargs: Any) -> Any:
            proc = await real_exec(*args, **kwargs)
            created.append(proc)
            return proc

        with patch("asyncio.create_subprocess_exec", new=_spy):
            await processor.process(exchange, ExecutionContext())

        assert exchange.status == ExchangeStatus.failed
        assert "timed out" in (exchange.error or "").lower()
        assert created, "subprocess не был создан"
        assert created[0].returncode is not None, "дочерний процесс не убит по таймауту"

    async def test_without_whitelist_command_is_rejected(self) -> None:
        """D2: ``allowed_commands=None`` → fail-closed, команда не выполняется."""
        processor = ShellExecProcessor(command="echo", args=["hi"], timeout_seconds=1.0)
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[assignment]
        exchange = _exchange()

        mock_exec = AsyncMock()
        with patch("asyncio.create_subprocess_exec", new=mock_exec):
            await processor.process(exchange, ExecutionContext())

        assert exchange.status == ExchangeStatus.failed
        assert "whitelist" in (exchange.error or "").lower()
        mock_exec.assert_not_called()

    async def test_command_outside_whitelist_is_rejected(self) -> None:
        """Команда вне whitelist отклоняется (регрессия)."""
        processor = ShellExecProcessor(
            command="rm", args=["-rf", "/"], allowed_commands=["echo"]
        )
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[assignment]
        exchange = _exchange()

        mock_exec = AsyncMock()
        with patch("asyncio.create_subprocess_exec", new=mock_exec):
            await processor.process(exchange, ExecutionContext())

        assert exchange.status == ExchangeStatus.failed
        assert "whitelist" in (exchange.error or "").lower()
        mock_exec.assert_not_called()


class _FakeIMAP:
    """Минимальный IMAP-клиент (все вызовы — успешные, пустой mailbox)."""

    instances: list["_FakeIMAP"] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        _FakeIMAP.instances.append(self)

    def login(self, *args: Any, **kwargs: Any) -> tuple[str, list[Any]]:
        return ("OK", [])

    def select(self, *args: Any, **kwargs: Any) -> tuple[str, list[Any]]:
        return ("OK", [])

    def search(self, *args: Any, **kwargs: Any) -> tuple[str, list[Any]]:
        return ("OK", [b""])

    def fetch(self, *args: Any, **kwargs: Any) -> tuple[str, list[Any]]:
        return ("OK", [])

    def logout(self) -> tuple[str, list[Any]]:
        return ("BYE", [])


class _HangingIMAP(_FakeIMAP):
    """IMAP-клиент, зависающий на connect (имитация мёртвого сокета)."""

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        time.sleep(2.0)
        super().__init__(host, port, timeout)


@pytest.mark.unit
class TestEmailReadFaultTolerance:
    """EmailReadProcessor: IMAP без timeout → поток executor'а висит вечно."""

    async def test_socket_timeout_is_passed_to_imap(self) -> None:
        processor = EmailReadProcessor(host="imap.example.com", port=993, timeout=5.0)
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[assignment]
        exchange = _exchange()
        _FakeIMAP.instances.clear()

        with patch("imaplib.IMAP4_SSL", new=_FakeIMAP):
            await processor.process(exchange, ExecutionContext())

        assert _FakeIMAP.instances, "IMAP-соединение не создано"
        assert _FakeIMAP.instances[0].timeout == 5.0, "socket-timeout не передан в IMAP"

    async def test_timeout_fails_exchange_instead_of_hanging(self) -> None:
        processor = EmailReadProcessor(host="imap.example.com", port=993, timeout=0.2)
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[assignment]
        exchange = _exchange()

        with patch("imaplib.IMAP4_SSL", new=_HangingIMAP):
            started = time.monotonic()
            await processor.process(exchange, ExecutionContext())
            elapsed = time.monotonic() - started

        assert elapsed < 1.5, "IMAP-чтение не ограничено таймаутом"
        assert exchange.status == ExchangeStatus.failed
        assert "timed out" in (exchange.error or "").lower()
