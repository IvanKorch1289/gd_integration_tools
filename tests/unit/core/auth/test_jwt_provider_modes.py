"""Контрактные тесты режима JWT-backend и выпуска токенов (ADR-0411).

Покрытие:
* DI-провайдер строит backend по алгоритму: HS* → secret, RS*/ES* → PEM/JWKS;
* «тихого» widening нет: ``jwks_url`` не добавляет RS256 к HS256-режиму;
* симметричный секрет не подставляется в асимметричный режим;
* асимметричный режим без источника ключа → fail-closed (ValueError);
* выпуск токена в RS256-режиме: подпись приватным ключом, проверка публичным;
* запрет «тихого» downgrade при явном ``alg``;
* контракт конфигурации: поля ``security.jwt_*`` и допустимые алгоритмы.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from joserfc import jwt as joserfc_jwt
from pydantic import SecretStr, ValidationError

from src.backend.core.auth.jwt_signing import encode_token, resolve_signing_params
from src.backend.core.config.security import SecureSettings
from src.backend.core.di.providers import auth as auth_provider
from src.backend.core.security.jwt_keys import write_keypair

HS_SECRET = "supersecretkeywithatleast32characters!!"


def _settings(**overrides: Any) -> SimpleNamespace:
    """Собирает объект настроек, похожий на ``SecureSettings``."""
    base: dict[str, Any] = {
        "secret_key": SecretStr(HS_SECRET),
        "algorithm": "HS256",
        "token_lifetime": 3600,
        "jwks_url": "",
        "jwks_cache_ttl": 300,
        "jwks_fetch_timeout": 5.0,
        "jwt_leeway": 60,
        "jwt_blacklist_enabled": False,
        "jwt_private_key_path": "",
        "jwt_public_key_path": "",
        "jwt_kid": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _clear_provider_cache() -> Any:
    """Сбрасывает singleton-backend между тестами."""
    auth_provider.set_jwt_backend_provider(None)
    yield
    auth_provider.set_jwt_backend_provider(None)


@pytest.fixture
def keypair(tmp_path: Path) -> Any:
    """Выпускает RSA-ключевую пару во временном каталоге."""
    return write_keypair(tmp_path / "keys")


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Any) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.security.secure_settings", settings, raising=True
    )


class TestProviderModes:
    """DI-провайдер: режим backend'а определяется алгоритмом."""

    def test_symmetric_mode_uses_secret_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, _settings(algorithm="HS256"))
        backend = auth_provider.get_jwt_backend_provider()
        assert backend.algorithms == ["HS256"]
        assert backend.secret == HS_SECRET
        assert backend.jwks is None
        assert backend.public_key is None

    def test_jwks_url_does_not_widen_hs256_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Раньше jwks_url молча добавлял RS256 к HS256 — algorithm confusion."""
        _patch_settings(
            monkeypatch, _settings(algorithm="HS256", jwks_url="https://idp/jwks.json")
        )
        backend = auth_provider.get_jwt_backend_provider()
        assert backend.algorithms == ["HS256"]
        assert backend.jwks is None

    def test_asymmetric_mode_with_pem_public_key(
        self, monkeypatch: pytest.MonkeyPatch, keypair: Any
    ) -> None:
        _patch_settings(
            monkeypatch,
            _settings(
                algorithm="RS256",
                jwt_public_key_path=str(keypair.public_path),
                jwt_kid=keypair.kid,
            ),
        )
        backend = auth_provider.get_jwt_backend_provider()
        assert backend.algorithms == ["RS256"]
        assert backend.secret is None
        assert backend.jwks is None
        assert backend.public_key is not None
        assert backend.kid == keypair.kid

    def test_asymmetric_mode_with_jwks_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(
            monkeypatch, _settings(algorithm="RS256", jwks_url="https://idp/jwks.json")
        )
        backend = auth_provider.get_jwt_backend_provider()
        assert backend.algorithms == ["RS256"]
        assert backend.secret is None
        assert backend.jwks is not None
        assert backend.public_key is None

    def test_asymmetric_mode_without_key_source_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, _settings(algorithm="RS256"))
        with pytest.raises(ValueError, match="jwks_url"):
            auth_provider.get_jwt_backend_provider()


class TestSigning:
    """Выпуск токенов по конфигурации (``jwt_signing``)."""

    def test_hs256_signing_uses_configured_secret(self) -> None:
        params = resolve_signing_params(_settings(algorithm="HS256"))
        assert params.alg == "HS256"
        assert params.secret == HS_SECRET
        assert params.private_key is None

    def test_rs256_signing_requires_private_key(self) -> None:
        with pytest.raises(ValueError, match="jwt_private_key_path"):
            resolve_signing_params(_settings(algorithm="RS256"))

    def test_rs256_signing_resolves_private_key_and_kid(self, keypair: Any) -> None:
        settings = _settings(
            algorithm="RS256", jwt_private_key_path=str(keypair.private_path)
        )
        params = resolve_signing_params(settings)
        assert params.alg == "RS256"
        assert params.secret is None
        assert params.private_key is not None
        assert params.kid == keypair.kid

    def test_rs256_token_signed_and_verified_with_public_key(
        self, keypair: Any
    ) -> None:
        settings = _settings(
            algorithm="RS256", jwt_private_key_path=str(keypair.private_path)
        )
        token, expires = encode_token("user-1", {"role": "admin"}, settings=settings)
        assert expires == 3600
        from src.backend.core.security.jwt_keys import load_public_key_pem

        decoded = joserfc_jwt.decode(
            token, key=load_public_key_pem(keypair.public_path), algorithms=["RS256"]
        )
        assert decoded.claims["sub"] == "user-1"
        assert decoded.claims["role"] == "admin"
        assert decoded.header["kid"] == keypair.kid

    def test_explicit_downgrade_algorithm_rejected(self, keypair: Any) -> None:
        settings = _settings(
            algorithm="RS256", jwt_private_key_path=str(keypair.private_path)
        )
        with pytest.raises(ValueError, match="downgrade"):
            encode_token("user-1", alg="HS256", secret=HS_SECRET, settings=settings)


class TestConfigContract:
    """Контракт конфигурации (``SecureSettings``)."""

    def test_asymmetric_key_fields_exist(self) -> None:
        for name in ("jwt_private_key_path", "jwt_public_key_path", "jwt_kid"):
            assert name in SecureSettings.model_fields

    def test_algorithm_allows_rs256_and_es256(self) -> None:
        annotation = SecureSettings.model_fields["algorithm"].annotation
        assert "RS256" in getattr(annotation, "__args__", ())
        assert "ES256" in getattr(annotation, "__args__", ())
        assert "HS256" in getattr(annotation, "__args__", ())

    def test_unknown_algorithm_rejected(self) -> None:
        assert "XX999" not in getattr(
            SecureSettings.model_fields["algorithm"].annotation, "__args__", ()
        )

    def test_key_paths_default_to_empty(self) -> None:
        for name in ("jwt_private_key_path", "jwt_public_key_path", "jwt_kid"):
            assert SecureSettings.model_fields[name].default == ""

    def test_algorithm_literal_validation(self) -> None:
        """Проверка, что Literal отвергает неизвестный алгоритм."""
        with pytest.raises(ValidationError):
            SecureSettings.model_validate(
                {
                    "token_lifetime": 3600,
                    "refresh_token_lifetime": 4800,
                    "secret_key": HS_SECRET,
                    "algorithm": "XX999",
                    "api_key": "key",
                    "allowed_hosts": ["localhost"],
                    "routes_without_api_key": ["/health"],
                    "admin_ips": ["127.0.0.1"],
                    "admin_routes": ["/admin"],
                    "request_timeout": 20.0,
                    "rate_limit": 100,
                    "rate_time_measure_seconds": 60,
                }
            )
