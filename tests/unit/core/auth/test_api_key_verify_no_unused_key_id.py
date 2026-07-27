"""Regression: ``core/auth/facade.py`` had ``key_id = f"{parts[0]}_{parts[1]}"``
unused (F841). The fix removes the local. We verify the API key path
still authenticates correctly via the underlying manager."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.backend.core.auth.facade import AuthFacade


@dataclass
class _FakeKeyInfo:
    is_active: bool = True
    key_hash: str = "argon2id$fake"
    client_id: str = "client-1"
    version: int = 1


class TestApiKeyVerifyNoUnusedKeyId:
    @pytest.mark.asyncio
    async def test_valid_api_key_authenticates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facade = AuthFacade()

        async def _validate_key(api_key: str) -> _FakeKeyInfo:
            return _FakeKeyInfo()

        class _StubManager:
            async def validate_key(self, api_key: str) -> _FakeKeyInfo:
                return await _validate_key(api_key)

        class _StubApiKey:
            def verify(self, plain: str, hashed: str) -> bool:
                return True

        monkeypatch.setattr(
            "src.backend.core.auth.api_key_backend.APIKeyAuth",
            lambda: _StubApiKey(),
        )
        monkeypatch.setattr(
            "src.backend.core.di.providers.auth.get_api_key_manager_provider",
            lambda: _StubManager(),
        )

        result = await facade._verify_api_key("ak_kid_secret42")
        assert result.is_authenticated is True
        assert result.method == "api_key"
        assert result.subject == "client-1"

    @pytest.mark.asyncio
    async def test_invalid_format_rejected(self) -> None:
        facade = AuthFacade()
        assert (await facade._verify_api_key("not-api-key")).is_authenticated is False
        assert (await facade._verify_api_key("ak_only_one")).is_authenticated is False
        assert (await facade._verify_api_key("ak_a_b_c")).is_authenticated is False
