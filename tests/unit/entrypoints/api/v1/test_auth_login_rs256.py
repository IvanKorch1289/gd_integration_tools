"""Тесты выпуска JWT в режиме RS256 через ``POST /auth/login`` (ADR-0411).

Покрытие:
* в асимметричном режиме login выпускает RS256-токен с ``kid``;
* токен проверяется публичным ключом (round-trip);
* в симметричном режиме выпускается HS256-токен (регрессия);
* в асимметричном режиме shared secret не используется.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import OctKey
from pydantic import SecretStr

from src.backend.core.security.jwt_keys import load_public_key_pem, write_keypair

HS_SECRET = "supersecretkeywithatleast32characters!!"


def _settings(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "secret_key": SecretStr(HS_SECRET),
        "algorithm": "HS256",
        "token_lifetime": 3600,
        "jwt_private_key_path": "",
        "jwt_public_key_path": "",
        "jwt_kid": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def keypair(tmp_path: Path) -> Any:
    return write_keypair(tmp_path / "keys")


def _client() -> TestClient:
    from src.backend.entrypoints.api.v1.endpoints.auth_login import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _login(client: TestClient) -> Any:
    mock_user = MagicMock()
    mock_user.username = "alice"
    mock_user.is_superuser = False

    async def fake_login(*args: Any, **kwargs: Any) -> Any:
        return mock_user

    with patch(
        "src.backend.entrypoints.api.v1.endpoints.auth_login._get_user_service",
        AsyncMock(return_value=MagicMock(login_with_method=fake_login)),
    ):
        return client.post(
            "/api/v1/auth/login",
            json={"method": "password", "username": "alice", "password": "correct"},
        )


def test_login_issues_rs256_token_signed_with_private_key(
    monkeypatch: pytest.MonkeyPatch, keypair: Any
) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.security.secure_settings",
        _settings(
            algorithm="RS256",
            jwt_private_key_path=str(keypair.private_path),
            jwt_kid=keypair.kid,
        ),
        raising=True,
    )
    response = _login(_client())
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]

    decoded = joserfc_jwt.decode(
        token, key=load_public_key_pem(keypair.public_path), algorithms=["RS256"]
    )
    assert decoded.header["alg"] == "RS256"
    assert decoded.header["kid"] == keypair.kid
    assert decoded.claims["sub"] == "alice"


def test_login_issues_hs256_token_in_symmetric_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.security.secure_settings",
        _settings(algorithm="HS256"),
        raising=True,
    )
    response = _login(_client())
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]

    header = joserfc_jwt.decode(
        token, key=OctKey.import_key(HS_SECRET), algorithms=["HS256"]
    )
    assert header.header["alg"] == "HS256"
    assert header.claims["sub"] == "alice"


def test_login_in_asymmetric_mode_without_private_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.backend.core.config.security.secure_settings",
        _settings(algorithm="RS256"),
        raising=True,
    )
    with pytest.raises(ValueError, match="jwt_private_key_path"):
        _login(_client())
