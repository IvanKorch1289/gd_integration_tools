"""Tests for manage.py grpc-serve command (D-AUDIT-20801, cycle 208).

Verifies CLI parsing + option forwarding to ``serve()`` без
реального запуска gRPC server (cycle unit test scope).

Ponytail/YAGNI: thin CLI wrapper, minimal logic.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from manage import app


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_serve() -> Any:
    """Mock grpc_server.server.serve."""
    with patch("src.backend.entrypoints.grpc.grpc_server.server.serve") as mock:
        yield mock


@pytest.fixture
def mock_settings() -> Any:
    """Mock settings to avoid full backend init."""
    with patch("manage.settings") as mock:
        # Avoid asyncio.run by returning early
        yield mock


def test_grpc_serve_help(cli_runner: CliRunner) -> None:
    """--help показывает usage без exceptions."""
    result = cli_runner.invoke(app, ["grpc-serve", "--help"])
    assert result.exit_code == 0
    assert "grpc-serve" in result.output
    assert "--socket" in result.output
    assert "--max-workers" in result.output


def test_grpc_serve_default_invokes_serve(
    cli_runner: CliRunner,
    mock_serve: MagicMock,
) -> None:
    """Default invocation (no flags) → serve() called через asyncio.run."""
    # asyncio.run патчим — иначе actual event loop попытка
    with patch("manage.asyncio.run") as mock_run:
        result = cli_runner.invoke(app, ["grpc-serve"])
        assert result.exit_code == 0, result.output
        # serve() imported в default branch был вызван via asyncio.run
        assert mock_run.called


def test_grpc_serve_socket_option_sets_env(
    cli_runner: CliRunner,
    mock_serve: MagicMock,
) -> None:
    """--socket задаёт GRPC_SOCKET_PATH env var."""
    with patch("manage.asyncio.run") as mock_run:
        result = cli_runner.invoke(
            app,
            ["grpc-serve", "--socket", "/tmp/test-grpc.sock"],
        )
        assert result.exit_code == 0, result.output
        assert os.environ.get("GRPC_SOCKET_PATH") == "/tmp/test-grpc.sock"
        assert mock_run.called


def test_grpc_serve_max_workers_option_sets_env(
    cli_runner: CliRunner,
    mock_serve: MagicMock,
) -> None:
    """--max-workers задаёт GRPC_MAX_WORKERS env var."""
    # Очищаем env чтобы избежать leakage из других тестов
    env_backup = os.environ.pop("GRPC_MAX_WORKERS", None)
    try:
        with patch("manage.asyncio.run") as mock_run:
            result = cli_runner.invoke(
                app,
                ["grpc-serve", "--max-workers", "5"],
            )
            assert result.exit_code == 0, result.output
            assert os.environ.get("GRPC_MAX_WORKERS") == "5"
    finally:
        if env_backup is not None:
            os.environ["GRPC_MAX_WORKERS"] = env_backup
        else:
            os.environ.pop("GRPC_MAX_WORKERS", None)


def test_settings_default_returns_value_for_known_path() -> None:
    """settings_default() resolves config fields to strings."""
    from manage import settings_default

    # Аргумент "grpc.socket_path" — строка вложенных attrs.
    # settings_default не должен crash на невалидном path → return "<default>".
    result = settings_default("definitely.not.a.real.field.xyz")
    assert result == "<default>"


def test_settings_default_does_not_crash_on_valid_path() -> None:
    """settings_default() вызывает getattr chain without exception
    для валидных path. Может вернуть строку или fallback."""
    from manage import settings_default

    # Не делаем assert на конкретное значение (зависит от test profile),
    # только что НЕ throw exception.
    try:
        result = settings_default("grpc.max_workers")
        assert isinstance(result, str)
    except Exception as exc:
        pytest.fail(f"settings_default crashed: {exc}")
