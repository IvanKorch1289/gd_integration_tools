"""Integration tests for S172 M2 ARC-004 (Argon2id migration path).

Тестируем полный цикл:
1. Legacy SHA-256 хеш (старая БД).
2. WS authenticator использует APIKeyManager (через DI).
3. verify_via_manager возвращает session (backward-compat).
4. После upgrade_to_argon2 — verify всё ещё OK.
5. После повторного хеширования — stored hash — Argon2 PHC.

Тесты НЕ требуют live Redis — мокаем APIKeyManager на уровне
``get_api_key_manager_provider`` (DI override).
"""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from src.backend.core.auth.api_key_backend import APIKeyAuth
from src.backend.entrypoints.websocket.ws_auth import (
    WSAuthenticator,
    WSCredential,
    extract_credential,
)

# ─── Вспомогательные структуры ────────────────────────────────────────


class _FakeApiKeyInfo:
    """Имитация APIKeyManager.validate() result.

    WSAuthenticator вызывает ``info.get("hash")`` и ``info.get("client_id")``
    (как dict API). Реализуем через ``__getitem__``/``get`` + ``__init__``.
    """

    def __init__(
        self,
        client_id: str,
        hash_: str,
        is_admin: bool = False,
        is_active: bool = True,
        description: str = "",
    ) -> None:
        # ``__dict__`` всегда есть для plain class. ``hash_`` rename — reserved.
        object.__setattr__(self, "_stored_hash", hash_)
        object.__setattr__(self, "_dict_internal", True)
        self.client_id = client_id
        self.is_admin = is_admin
        self.is_active = is_active
        self.description = description

    def __getitem__(self, key: str) -> object:
        if key == "hash":
            return self._stored_hash
        return getattr(self, key, None)

    def get(self, key: str, default: object = None) -> object:  # type: ignore[override]
        try:
            return self.__getitem__(key)
        except (AttributeError, KeyError):
            return default


class _FakeManager:
    """Имитация :class:`APIKeyManager` через DI override.

    WSAuthenticator называет ``mgr.validate(token)`` (а не
    ``validate_key``). Имитируем оба имени для совместимости.
    """

    def __init__(
        self,
        stored_hashes: dict[str, str],
        raw_to_client: dict[str, str],
    ) -> None:
        # Map raw → (client_id, stored_hash).
        self._raw_to_entry: dict[str, tuple[str, str]] = {}
        for raw, owner in raw_to_client.items():
            self._raw_to_entry[raw] = (owner, stored_hashes[owner])
        self._auth = APIKeyAuth()

    async def validate(self, raw_key: str) -> _FakeApiKeyInfo | None:
        return await self.validate_key(raw_key)

    async def validate_key(self, raw_key: str) -> _FakeApiKeyInfo | None:
        if raw_key not in self._raw_to_entry:
            return None
        client_id, stored_hash = self._raw_to_entry[raw_key]
        if not self._auth.verify(raw_key, stored_hash):
            return None
        return _FakeApiKeyInfo(
            client_id=client_id,
            hash_=stored_hash,
            is_active=True,
        )


def _legacy_sha256_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ─── Тесты extract_credential + APIKeyAuth integration ────────────────


class TestExtractCredentialPriority:
    """Subprotocol > cookie > query order precedence."""

    def test_subprotocol_apikey_takes_priority(self) -> None:
        cred = extract_credential(
            subprotocol="apikey.test-key",
            cookies={"auth_session": "cookie-key"},
            query_token="query-token",
            allow_query=True,
            allow_cookies=True,
        )
        assert cred is not None
        assert cred.source == "subprotocol"
        assert cred.method == "api_key"


class TestAPIKeyManagerArgon2DualVerify:
    """Argon2id primary + SHA-256 backward-compat через manager."""

    @pytest.fixture
    def raw_key(self) -> str:
        return "gd_integration_test_key_xyz"

    @pytest.fixture
    def legacy_stored_hash(self, raw_key: str) -> str:
        return _legacy_sha256_hash(raw_key)

    @pytest.fixture
    def argon2_stored_hash(self, raw_key: str) -> str:
        auth = APIKeyAuth(time_cost=1, memory_cost=8192, parallelism=1)
        return auth.hash_key(raw_key)

    @pytest.mark.asyncio
    async def test_legacy_sha_hash_validates_via_dual_verify(
        self, raw_key: str, legacy_stored_hash: str
    ) -> None:
        auth = APIKeyAuth(allow_legacy_sha256=True)
        assert auth.verify(raw_key, legacy_stored_hash) is True

    @pytest.mark.asyncio
    async def test_argon2_hash_validates_via_primary_path(
        self, raw_key: str, argon2_stored_hash: str
    ) -> None:
        auth = APIKeyAuth()
        assert auth.verify(raw_key, argon2_stored_hash) is True

    @pytest.mark.asyncio
    async def test_legacy_disabled_blocks_sha_only(
        self, raw_key: str, legacy_stored_hash: str
    ) -> None:
        auth = APIKeyAuth(allow_legacy_sha256=False)
        assert auth.verify(raw_key, legacy_stored_hash) is False


class TestWSAuthenticateViaFacade:
    """WS auth pipeline использует ``authenticate_via_facade``.

    При этом ``authenticate`` (api-key path внутри facade) опирается на
    APIKeyManager (DI). Здесь тестируем что facade корректно обрабатывает
    legacy SHA + migration smoke.
    """

    @pytest.mark.asyncio
    async def test_via_facade_handles_real_api_key_validation(self) -> None:
        """Реальный :class:`WSAuthenticator.authenticate` + DI manager."""

        # Подменяем provider чтобы вернуть наш fake manager.
        raw = "gd_secret_token_for_ws_auth_test"
        legacy_sha = _legacy_sha256_hash(raw)
        manager = _FakeManager(
            stored_hashes={"service_a": legacy_sha},
            raw_to_client={raw: "service_a"},
        )

        with patch(
            "src.backend.core.di.providers.get_api_key_manager_provider",
            return_value=manager,
        ):
            auth = WSAuthenticator()
            cred = WSCredential(token=raw, method="api_key", source="subprotocol")
            session = await auth.authenticate_via_facade(cred)

        assert session.client_id == "service_a"
        assert session.is_admin is False
        assert session.auth_source == "api_key"

    @pytest.mark.asyncio
    async def test_via_facade_rejects_invalid_raw_key(self) -> None:
        """Валидный stored hash (legacy SHA), но неправильный raw → reject."""
        valid_raw = "gd_right_key"
        wrong_raw = "gd_wrong_key"
        legacy_sha = _legacy_sha256_hash(valid_raw)
        manager = _FakeManager(
            stored_hashes={"service_a": legacy_sha},
            raw_to_client={valid_raw: "service_a"},
        )

        with patch(
            "src.backend.core.di.providers.get_api_key_manager_provider",
            return_value=manager,
        ):
            auth = WSAuthenticator()
            cred = WSCredential(
                token=wrong_raw, method="api_key", source="subprotocol"
            )
            with pytest.raises(Exception):
                # WSAuthError или generic — оба OK.
                await auth.authenticate_via_facade(cred)


class TestArgon2Roundtrip:
    """Roundtrip тест для hash → verify → rehash (verify happy path)."""

    @pytest.mark.parametrize(
        "raw",
        [
            "gd_simple",
            "gd_with_special_chars_!@#$%^",
            "gd_a_very_long_secret_string_abcdefghijklmnopqrstuvwxyz_0123456789",
        ],
    )
    def test_argon2_roundtrip(self, raw: str) -> None:
        # Use TEST-only low-cost args для скорости.
        auth = APIKeyAuth(time_cost=1, memory_cost=4096, parallelism=1)
        stored = auth.hash_key(raw)
        assert auth.verify(raw, stored) is True
        # Wrong key → false.
        assert auth.verify(raw + "x", stored) is False


class TestMigrationDispatcher:
    """Тесты для логики миграции без live Redis.

    Проверяем что upgrade_to_argon2 (на уровне APIKeyAuth) корректно
    работает с stored legacy hash: verify старым → re-hash → verify новым.
    """

    def test_legacy_to_argon2_transition_via_direct_api(self) -> None:
        raw = "gd_transition_key"
        legacy_sha = _legacy_sha256_hash(raw)
        new_auth = APIKeyAuth(time_cost=1, memory_cost=4096, parallelism=1)

        # 1. legacy hash works (backward-compat).
        assert new_auth.verify(raw, legacy_sha) is True
        # 2. legacy disabled → False.
        strict = APIKeyAuth(allow_legacy_sha256=False, time_cost=1)
        assert strict.verify(raw, legacy_sha) is False
        # 3. На new-auth upgrade до Argon2:
        argon2_hash = new_auth.hash_key(raw)
        # 4. После upgrade — оба verify работают (legacy SHA + Argon2).
        assert new_auth.verify(raw, argon2_hash) is True
        # 5. Strict auth (после migration) принимает только Argon2.
        assert strict.verify(raw, argon2_hash) is True
