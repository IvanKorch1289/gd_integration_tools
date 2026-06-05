"""Unit tests for setup_middlewares."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from src.backend.entrypoints.middlewares.setup_middlewares import (
    build_default_registry,
    setup_middlewares,
)


class TestBuildDefaultRegistry:
    """Tests for build_default_registry."""

    def test_returns_registry(self) -> None:
        mock_registry = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.registry.MiddlewareRegistry",
            return_value=mock_registry,
        ):
            with patch(
                "src.backend.entrypoints.middlewares.setup_middlewares.settings",
                MagicMock(
                    secure=MagicMock(
                        cors_origins=["*"],
                        cors_allow_credentials=True,
                        cors_allow_methods=["GET"],
                        cors_allow_headers=["*"],
                        allowed_hosts=["*"],
                    ),
                    app=MagicMock(
                        compression_brotli=False,
                        brotli_minimum_size=100,
                        brotli_quality=4,
                        gzip_minimum_size=500,
                        gzip_compresslevel=6,
                        title="test",
                    ),
                ),
            ):
                registry = build_default_registry()
        assert registry is mock_registry
        assert mock_registry.register_builtin.call_count >= 10


class TestSetupMiddlewares:
    """Tests for setup_middlewares."""

    def test_applies_to_app(self) -> None:
        app = FastAPI()
        mock_registry = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.setup_middlewares.build_default_registry",
            return_value=mock_registry,
        ):
            setup_middlewares(app)
        mock_registry.register_from_entry_points.assert_called_once()
        mock_registry.apply_to_app.assert_called_once_with(app)

    def test_raises_on_entry_point_error(self) -> None:
        app = FastAPI()
        mock_registry = MagicMock()
        mock_registry.register_from_entry_points.side_effect = ValueError("bad ep")
        with patch(
            "src.backend.entrypoints.middlewares.setup_middlewares.build_default_registry",
            return_value=mock_registry,
        ):
            with pytest.raises(RuntimeError, match="entry-points"):
                setup_middlewares(app)

    def test_raises_on_apply_error(self) -> None:
        app = FastAPI()
        mock_registry = MagicMock()
        mock_registry.apply_to_app.side_effect = TypeError("bad mw")
        with patch(
            "src.backend.entrypoints.middlewares.setup_middlewares.build_default_registry",
            return_value=mock_registry,
        ):
            with pytest.raises(RuntimeError, match="конфигурации"):
                setup_middlewares(app)
