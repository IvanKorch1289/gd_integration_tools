"""Unit tests for src.backend.main entrypoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.backend import main
from src.backend.plugins.composition import app_factory

# ``_mount_mcp_http`` переехал из ``src.backend.main`` в
# ``src.backend.plugins.composition.app_factory`` (D-AUDIT-20807, cycle 216)
# и теперь принимает FastAPI-приложение аргументом, а не берёт module-global.
# Тесты ниже всё ещё обращались к ``main._mount_mcp_http`` и падали с
# AttributeError: module 'src.backend.main' has no attribute '_mount_mcp_http'.


def test_mount_mcp_http_skipped_when_disabled() -> None:
    mock_app = MagicMock()
    with patch("src.backend.core.config.ai_stack.mcp_settings") as mock_settings:
        mock_settings.http_enabled = False
        app_factory._mount_mcp_http(mock_app)
    mock_app.mount.assert_not_called()


def test_mount_mcp_http_skipped_on_import_error() -> None:
    # Чтобы ``from src.backend.core.config.ai_stack import mcp_settings``
    # действительно бросил ImportError, модуль надо убрать из sys.modules
    # значением None (тогда import падает: "import of X halted; None in
    # sys.modules"). Раньше здесь стоял patch(..., side_effect=ImportError),
    # но side_effect срабатывает только при ВЫЗОВЕ мока, а ``from ... import``
    # лишь связывает имя — ImportError не возникал, и тест проходил только
    # потому, что fastmcp не был установлен и create_mcp_http_app() падал
    # по другой причине. Проверка была зелёной не по той причине, что думали.
    mock_app = MagicMock()
    with patch.dict("sys.modules", {"src.backend.core.config.ai_stack": None}):
        app_factory._mount_mcp_http(mock_app)
    mock_app.mount.assert_not_called()


def test_mount_mcp_http_mounts_when_enabled() -> None:
    mock_app = MagicMock()
    mock_asgi = MagicMock()
    with patch("src.backend.core.config.ai_stack.mcp_settings") as mock_settings:
        mock_settings.http_enabled = True
        mock_settings.bind_path = "/mcp"
        with patch(
            "src.backend.entrypoints.mcp.http_server.create_mcp_http_app"
        ) as mock_create:
            # create_mcp_http_app() возвращает пару (asgi_app, lifespan).
            mock_create.return_value = (mock_asgi, MagicMock())
            app_factory._mount_mcp_http(mock_app)
            mock_app.mount.assert_called_once_with("/mcp", mock_asgi)


def test_mount_mcp_http_logs_warning_on_exception() -> None:
    mock_app = MagicMock()
    with patch("src.backend.core.config.ai_stack.mcp_settings") as mock_settings:
        mock_settings.http_enabled = True
        with patch(
            "src.backend.entrypoints.mcp.http_server.create_mcp_http_app",
            side_effect=RuntimeError("fail"),
        ):
            app_factory._mount_mcp_http(mock_app)
    mock_app.mount.assert_not_called()


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
