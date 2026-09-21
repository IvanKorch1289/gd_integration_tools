"""Unit tests for src.backend.core.config.auth."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.auth import (
    AuthConfig,
    ExpressJwtConfig,
    JwtConfig,
    build_auth_config,
)


class TestJwtConfig:
    def test_defaults(self) -> None:
        cfg = JwtConfig(secret_key="s" * 32)
        assert cfg.algorithm == "HS256"
        assert cfg.token_lifetime == 3600

    def test_custom_values(self) -> None:
        cfg = JwtConfig(secret_key="k" * 32, algorithm="HS512", token_lifetime=7200)
        assert cfg.algorithm == "HS512"
        assert cfg.token_lifetime == 7200

    def test_validation_token_lifetime_too_low(self) -> None:
        with pytest.raises(Exception):
            JwtConfig(secret_key="s" * 32, token_lifetime=30)


class TestExpressJwtConfig:
    def test_defaults(self) -> None:
        cfg = ExpressJwtConfig()
        assert cfg.bot_id == ""
        assert cfg.secret_key == ""
        assert cfg.botx_host == ""
        assert cfg.enabled is False

    def test_custom_values(self) -> None:
        cfg = ExpressJwtConfig(
            bot_id="b1", secret_key="sk", botx_host="host.example", enabled=True
        )
        assert cfg.bot_id == "b1"
        assert cfg.secret_key == "sk"
        assert cfg.botx_host == "host.example"
        assert cfg.enabled is True


class TestAuthConfig:
    def test_fields(self) -> None:
        cfg = AuthConfig(
            api_key="ak1",
            jwt=JwtConfig(secret_key="s" * 32),
            express_jwt=ExpressJwtConfig(bot_id="b1"),
        )
        assert cfg.api_key == "ak1"
        assert cfg.jwt.secret_key == "s" * 32
        assert cfg.express_jwt.bot_id == "b1"


class TestBuildAuthConfig:
    def test_with_explicit_settings(self) -> None:
        secure = MagicMock()
        secure.secret_key = "secret123"
        secure.algorithm = "HS512"
        secure.token_lifetime = 7200
        secure.api_key = "ak1"

        express = MagicMock()
        express.bot_id = "b1"
        express.secret_key = "esk"
        express.botx_host = "host1"
        express.enabled = True

        cfg = build_auth_config(secure=secure, express=express)
        assert cfg.api_key == "ak1"
        assert cfg.jwt.secret_key == "secret123"
        assert cfg.jwt.algorithm == "HS512"
        assert cfg.jwt.token_lifetime == 7200
        assert cfg.express_jwt.bot_id == "b1"
        assert cfg.express_jwt.secret_key == "esk"
        assert cfg.express_jwt.botx_host == "host1"
        assert cfg.express_jwt.enabled is True

    def test_secret_key_with_get_secret_value(self) -> None:
        secure = MagicMock()
        secret = MagicMock()
        secret.get_secret_value.return_value = "hidden"
        secure.secret_key = secret
        secure.algorithm = "HS256"
        secure.token_lifetime = 3600
        secure.api_key = ""

        express = MagicMock()
        express.bot_id = ""
        express.secret_key = ""
        express.botx_host = ""
        express.enabled = False

        cfg = build_auth_config(secure=secure, express=express)
        assert cfg.jwt.secret_key == "hidden"

    def test_with_none_uses_singletons(self) -> None:
        with (
            patch("src.backend.core.config.security.secure_settings") as mock_secure,
            patch("src.backend.core.config.express.express_settings") as mock_express,
        ):
            mock_secure.secret_key = "singleton_secret"
            mock_secure.algorithm = "HS256"
            mock_secure.token_lifetime = 3600
            mock_secure.api_key = "api"

            mock_express.bot_id = ""
            mock_express.secret_key = ""
            mock_express.botx_host = ""
            mock_express.enabled = False

            cfg = build_auth_config()
            assert cfg.jwt.secret_key == "singleton_secret"
            assert cfg.api_key == "api"
