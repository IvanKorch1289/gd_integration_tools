"""Unit-тесты для SshCommandProcessor (S35 GAP-INT-2).

Тестирует:
- выполнение удалённой команды
- захват stdout, stderr, exit_code
- поднятие исключения при ненулевом exit_code
- аутентификацию по ключу
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.ssh_command import SshCommandProcessor


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


def _mock_asyncssh() -> MagicMock:
    """Создаёт мок-объект asyncssh с корректным поведением контекстного менеджера."""
    mock = MagicMock()
    mock.connect.return_value.__aenter__.return_value = AsyncMock()
    return mock


class TestSshCommandProcessor:
    """Тесты для SshCommandProcessor."""

    @pytest.mark.asyncio
    async def test_ssh_command_executes_remote_command(self) -> None:
        """Успешное выполнение remote-команды."""
        proc = SshCommandProcessor(
            host="192.168.1.10",
            command="ls -la /data",
            username="robot",
            key_file="/secrets/id_rsa",
        )
        exchange = _make_exchange()

        mock_result = MagicMock()
        mock_result.stdout = "file1.txt\nfile2.txt\n"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_asyncssh = _mock_asyncssh()
        mock_asyncssh.connect.return_value.__aenter__.return_value = mock_conn

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("ssh_result") is not None
        result = exchange.properties["ssh_result"]
        assert result["stdout"] == "file1.txt\nfile2.txt\n"
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_ssh_command_captures_stdout_stderr_exitcode(self) -> None:
        """Проверка захвата stdout, stderr и exit_code."""
        proc = SshCommandProcessor(
            host="server.example.com",
            command="ls /nonexistent",
        )
        exchange = _make_exchange()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "ls: cannot access '/nonexistent': No such file or directory"
        mock_result.exit_code = 2

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_asyncssh = _mock_asyncssh()
        mock_asyncssh.connect.return_value.__aenter__.return_value = mock_conn

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await proc.process(exchange, MagicMock())

        result = exchange.properties["ssh_result"]
        assert result["stdout"] == ""
        assert "cannot access" in result["stderr"]
        assert result["exit_code"] == 2

    @pytest.mark.asyncio
    async def test_ssh_command_raises_on_nonzero_exit(self) -> None:
        """При ненулевом exit_code и continue_on_error=False процессор
        устанавливает exchange в статус failed."""
        proc = SshCommandProcessor(
            host="192.168.1.10",
            command="exit 1",
            continue_on_error=False,
        )
        exchange = _make_exchange()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.exit_code = 1

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_asyncssh = _mock_asyncssh()
        mock_asyncssh.connect.return_value.__aenter__.return_value = mock_conn

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await proc.process(exchange, MagicMock())

        assert exchange.error is not None
        assert "exit code 1" in exchange.error or "code 1" in exchange.error

    @pytest.mark.asyncio
    async def test_ssh_command_key_file_auth(self) -> None:
        """Проверка аутентификации по ключу."""
        proc = SshCommandProcessor(
            host="192.168.1.10",
            command="whoami",
            username="robot",
            key_file="/secrets/id_rsa",
        )
        exchange = _make_exchange()

        mock_result = MagicMock()
        mock_result.stdout = "robot\n"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_asyncssh = _mock_asyncssh()
        mock_asyncssh.connect.return_value.__aenter__.return_value = mock_conn

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await proc.process(exchange, MagicMock())

            # Проверяем, что connect вызван с client_keys
            call_kwargs = mock_asyncssh.connect.call_args.kwargs
            assert call_kwargs["username"] == "robot"
            assert call_kwargs["client_keys"] == ["/secrets/id_rsa"]

    @pytest.mark.asyncio
    async def test_ssh_command_password_from_body(self) -> None:
        """Проверка извлечения пароля из body."""
        proc = SshCommandProcessor(
            host="192.168.1.10",
            command="ls",
            password_from="body",
        )
        exchange = _make_exchange(body={"password": "secret123"})

        mock_result = MagicMock()
        mock_result.stdout = "output\n"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_asyncssh = _mock_asyncssh()
        mock_asyncssh.connect.return_value.__aenter__.return_value = mock_conn

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await proc.process(exchange, MagicMock())

            call_kwargs = mock_asyncssh.connect.call_args.kwargs
            assert call_kwargs["password"] == "secret123"

    @pytest.mark.asyncio
    async def test_ssh_command_password_from_properties(self) -> None:
        """Проверка извлечения пароля из properties."""
        proc = SshCommandProcessor(
            host="192.168.1.10",
            command="ls",
            password_from="properties",
        )
        exchange = _make_exchange()
        exchange.set_property("password", "props_secret")

        mock_result = MagicMock()
        mock_result.stdout = "output\n"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_asyncssh = _mock_asyncssh()
        mock_asyncssh.connect.return_value.__aenter__.return_value = mock_conn

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await proc.process(exchange, MagicMock())

            call_kwargs = mock_asyncssh.connect.call_args.kwargs
            assert call_kwargs["password"] == "props_secret"

    @pytest.mark.asyncio
    async def test_ssh_command_continue_on_error(self) -> None:
        """При continue_on_error=True даже ненулевой exit_code
        не вызывает exchange.fail."""
        proc = SshCommandProcessor(
            host="192.168.1.10",
            command="exit 1",
            continue_on_error=True,
        )
        exchange = _make_exchange()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.exit_code = 1

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_asyncssh = _mock_asyncssh()
        mock_asyncssh.connect.return_value.__aenter__.return_value = mock_conn

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await proc.process(exchange, MagicMock())

        # exchange не должен быть в статусе failed
        assert exchange.error is None
        result = exchange.properties["ssh_result"]
        assert result["exit_code"] == 1

    def test_to_spec(self) -> None:
        """Проверка YAML round-trip spec."""
        proc = SshCommandProcessor(
            host="192.168.1.10",
            command="ls",
            username="robot",
            key_file="/keys/id_rsa",
            timeout=60.0,
            result_property="remote_result",
            continue_on_error=True,
        )
        spec = proc.to_spec()
        assert spec == {
            "ssh_exec": {
                "host": "192.168.1.10",
                "command": "ls",
                "username": "robot",
                "key_file": "/keys/id_rsa",
                "timeout": 60.0,
                "result_property": "remote_result",
                "continue_on_error": True,
            }
        }
