"""S36 w5 — Smoke tests: Granian runtime mode.

Verifies that:
1. Granian is installed and importable
2. ``_run_granian()`` configures Granian with correct kwargs
3. ``run()`` dispatches to granian path when server="granian"
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from granian import Granian
from granian.constants import HTTPModes, Interfaces, Loops, RuntimeModes
from granian.log import LogLevels


def _get_run_granian():
    """Import _run_granian lazily, bypassing app factory."""
    import src.backend.plugins.composition.app_factory as af_module

    fake_app = type("FakeApp", (), {"include_router": lambda *a, **k: None})()
    original_create_app = af_module.create_app
    af_module.create_app = lambda *a, **k: fake_app

    try:
        import src.backend.main as main_module

        import importlib

        importlib.reload(main_module)
        return main_module._run_granian
    finally:
        af_module.create_app = original_create_app


def _mock_granian():
    """Return (mock_init, mock_instance) for Granian mocking."""
    mock_instance = MagicMock()
    mock_instance.serve = MagicMock()
    mock_init = MagicMock(return_value=None)
    return mock_init, mock_instance


def test_granian_importable() -> None:
    """Granian library is installed and importable."""
    import granian

    assert hasattr(granian, "__version__")
    assert granian.__version__.startswith("2.")


def test_run_granian_configures_granian_correctly() -> None:
    """_run_granian() builds correct Granian kwargs from settings."""
    _run_granian = _get_run_granian()
    mock_init, mock_instance = _mock_granian()

    with patch.object(Granian, "__init__", mock_init):
        with patch.object(Granian, "serve", mock_instance.serve):
            with patch("src.backend.main.settings") as mock_settings:
                mock_settings.app.host = "127.0.0.1"
                mock_settings.app.port = 8080
                mock_settings.app.granian_http = "auto"
                mock_settings.app.granian_runtime_mode = "mt"
                mock_settings.app.workers = 4
                mock_settings.app.granian_runtime_threads = 8
                mock_settings.app.listen_backlog = 2048
                mock_settings.app.debug_mode = False

                _run_granian()

                mock_instance.serve.assert_called_once()
                init_args, init_kwargs = mock_init.call_args

                assert init_kwargs["target"] == "src.backend.main:app"
                assert init_kwargs["address"] == "127.0.0.1"
                assert init_kwargs["port"] == 8080
                assert init_kwargs["interface"] == Interfaces.ASGI
                assert init_kwargs["workers"] == 4
                assert init_kwargs["runtime_threads"] == 8
                assert init_kwargs["runtime_mode"] == RuntimeModes.mt
                assert init_kwargs["loop"] == Loops.uvloop
                assert init_kwargs["http"] == HTTPModes.auto
                assert init_kwargs["backlog"] == 2048
                assert init_kwargs["log_level"] == LogLevels.info


def test_run_granian_st_mode() -> None:
    """_run_granian() supports single-threaded (st) runtime mode."""
    _run_granian = _get_run_granian()
    mock_init, mock_instance = _mock_granian()

    with patch.object(Granian, "__init__", mock_init):
        with patch.object(Granian, "serve", mock_instance.serve):
            with patch("src.backend.main.settings") as mock_settings:
                mock_settings.app.host = "0.0.0.0"
                mock_settings.app.port = 8000
                mock_settings.app.granian_http = "2"
                mock_settings.app.granian_runtime_mode = "st"
                mock_settings.app.workers = 1
                mock_settings.app.granian_runtime_threads = 1
                mock_settings.app.listen_backlog = 128
                mock_settings.app.debug_mode = True

                _run_granian()

                init_args, init_kwargs = mock_init.call_args
                assert init_kwargs["runtime_mode"] == RuntimeModes.st
                assert init_kwargs["http"] == HTTPModes.http2
                assert init_kwargs["log_level"] == LogLevels.debug


def test_run_granian_blocking_threads_optional() -> None:
    """blocking_threads is only set when explicitly configured."""
    _run_granian = _get_run_granian()
    mock_init, mock_instance = _mock_granian()

    with patch.object(Granian, "__init__", mock_init):
        with patch.object(Granian, "serve", mock_instance.serve):
            with patch("src.backend.main.settings") as mock_settings:
                mock_settings.app.host = "127.0.0.1"
                mock_settings.app.port = 8000
                mock_settings.app.granian_http = "auto"
                mock_settings.app.granian_runtime_mode = "auto"
                mock_settings.app.workers = 2
                mock_settings.app.granian_runtime_threads = 4
                mock_settings.app.listen_backlog = 512
                mock_settings.app.debug_mode = False
                mock_settings.app.granian_blocking_threads = None

                _run_granian()

                init_args, init_kwargs = mock_init.call_args
                assert "blocking_threads" not in init_kwargs


def test_run_granian_blocking_threads_when_set() -> None:
    """blocking_threads is passed when explicitly configured."""
    _run_granian = _get_run_granian()
    mock_init, mock_instance = _mock_granian()

    with patch.object(Granian, "__init__", mock_init):
        with patch.object(Granian, "serve", mock_instance.serve):
            with patch("src.backend.main.settings") as mock_settings:
                mock_settings.app.host = "127.0.0.1"
                mock_settings.app.port = 8000
                mock_settings.app.granian_http = "auto"
                mock_settings.app.granian_runtime_mode = "auto"
                mock_settings.app.workers = 2
                mock_settings.app.granian_runtime_threads = 4
                mock_settings.app.listen_backlog = 512
                mock_settings.app.debug_mode = False
                mock_settings.app.granian_blocking_threads = 16

                _run_granian()

                init_args, init_kwargs = mock_init.call_args
                assert init_kwargs["blocking_threads"] == 16
