"""Unit tests for src.backend.main entrypoint."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.backend import main


@patch.object(main, "app", MagicMock())
def test_mount_mcp_http_skipped_when_disabled() -> None:
    with patch("src.backend.core.config.ai_stack.mcp_settings") as mock_settings:
        mock_settings.http_enabled = False
        main._mount_mcp_http()


@patch.object(main, "app", MagicMock())
def test_mount_mcp_http_skipped_on_import_error() -> None:
    # S146 W2: patch source location, not consumer.
    # ``_mount_mcp_http`` does ``from src.backend.core.config.ai_stack import mcp_settings``
    # inside the function body, so ``src.backend.main.mcp_settings`` is not
    # an importable attribute. Patch the source module instead.
    with patch("src.backend.core.config.ai_stack.mcp_settings", side_effect=ImportError):
        main._mount_mcp_http()


@patch.object(main, "app", MagicMock())
def test_mount_mcp_http_mounts_when_enabled() -> None:
    with patch("src.backend.core.config.ai_stack.mcp_settings") as mock_settings:
        mock_settings.http_enabled = True
        mock_settings.bind_path = "/mcp"
        with patch(
            "src.backend.entrypoints.mcp.http_server.create_mcp_http_app"
        ) as mock_create:
            mock_app = MagicMock()
            mock_create.return_value = mock_app
            main._mount_mcp_http()
            main.app.mount.assert_called_once_with("/mcp", mock_app)


@patch.object(main, "app", MagicMock())
def test_mount_mcp_http_logs_warning_on_exception() -> None:
    with patch("src.backend.core.config.ai_stack.mcp_settings") as mock_settings:
        mock_settings.http_enabled = True
        with patch(
            "src.backend.entrypoints.mcp.http_server.create_mcp_http_app",
            side_effect=RuntimeError("fail"),
        ):
            main._mount_mcp_http()


def test_run_uvicorn() -> None:
    with (
        patch("src.backend.main.uvicorn") as mock_uvicorn,
        patch.object(main.settings.app, "server", "uvicorn"),
        patch.object(main.settings.app, "environment", "development"),
        patch.object(main.settings.app, "debug_mode", True),
        patch.object(main.settings.app, "host", "0.0.0.0"),
        patch.object(main.settings.app, "port", 8000),
        patch.object(main.settings.app, "keep_alive_timeout", 5),
        patch.object(main.settings.app, "listen_backlog", 2048),
    ):
        main.run()
        mock_uvicorn.run.assert_called_once()
        kwargs = mock_uvicorn.run.call_args.kwargs
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 8000
        assert kwargs["reload"] is True


def test_run_granian() -> None:
    with (
        patch("src.backend.main.Granian") as mock_granian,
        patch.object(main.settings.app, "server", "granian"),
        patch.object(main.settings.app, "debug_mode", False),
        patch.object(main.settings.app, "host", "0.0.0.0"),
        patch.object(main.settings.app, "port", 8000),
        patch.object(main.settings.app, "workers", 4),
        patch.object(main.settings.app, "keep_alive_timeout", 5),
        patch.object(main.settings.app, "listen_backlog", 2048),
        patch.object(main.settings.app, "granian_http", "auto"),
        patch.object(main.settings.app, "granian_runtime_mode", "mt"),
        patch.object(main.settings.app, "granian_runtime_threads", 2),
        patch.object(main.settings.app, "granian_blocking_threads", None),
    ):
        main.run()
        mock_granian.assert_called_once()
        mock_granian.return_value.serve.assert_called_once()
