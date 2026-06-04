"""Unit tests for WSAuthenticator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.entrypoints.websocket.ws_auth import (
    WSAuthError,
    WSAuthenticator,
    WSSession,
    get_ws_authenticator,
)


class TestWSAuthenticator:
    """Tests for :class:`WSAuthenticator`."""

    @pytest.fixture
    def authenticator(self) -> WSAuthenticator:
        return WSAuthenticator()

    @pytest.mark.asyncio
    async def test_missing_token_raises(self, authenticator: WSAuthenticator) -> None:
        """authenticate with None token raises WSAuthError."""
        with pytest.raises(WSAuthError, match="Missing authentication token"):
            await authenticator.authenticate(None)

    @pytest.mark.asyncio
    async def test_valid_token_returns_session(
        self, authenticator: WSAuthenticator
    ) -> None:
        """authenticate returns WSSession for valid token."""
        mock_mgr = AsyncMock()
        mock_mgr.validate.return_value = {
            "hash": "abc123",
            "client_id": "client1",
            "is_admin": True,
        }

        with patch(
            "src.backend.core.di.providers.get_api_key_manager_provider",
            return_value=mock_mgr,
        ):
            session = await authenticator.authenticate("Bearer valid-token")

        assert isinstance(session, WSSession)
        assert session.client_id == "client1"
        assert session.api_key_hash == "abc123"
        assert session.is_admin is True

    @pytest.mark.asyncio
    async def test_invalid_api_key_raises(self, authenticator: WSAuthenticator) -> None:
        """authenticate raises when validate returns None."""
        mock_mgr = AsyncMock()
        mock_mgr.validate.return_value = None

        with patch(
            "src.backend.core.di.providers.get_api_key_manager_provider",
            return_value=mock_mgr,
        ):
            with pytest.raises(WSAuthError, match="Invalid API key"):
                await authenticator.authenticate("token")

    @pytest.mark.asyncio
    async def test_auth_failure_raises(self, authenticator: WSAuthenticator) -> None:
        """authenticate wraps generic exceptions."""
        mock_mgr = AsyncMock()
        mock_mgr.validate.side_effect = RuntimeError("boom")

        with patch(
            "src.backend.core.di.providers.get_api_key_manager_provider",
            return_value=mock_mgr,
        ):
            with pytest.raises(WSAuthError, match="Auth failed"):
                await authenticator.authenticate("token")

    @pytest.mark.asyncio
    async def test_load_groups_from_redis(self, authenticator: WSAuthenticator) -> None:
        """_load_groups returns set from redis smembers."""
        mock_redis = AsyncMock()
        mock_redis.smembers.return_value = [b"group1", b"group2"]

        with patch(
            "src.backend.core.di.providers.get_redis_kv_client_provider",
            return_value=mock_redis,
        ):
            groups = await authenticator._load_groups("hash123")

        assert groups == {"group1", "group2"}

    @pytest.mark.asyncio
    async def test_load_groups_empty_hash(self, authenticator: WSAuthenticator) -> None:
        """_load_groups returns empty set for empty hash."""
        groups = await authenticator._load_groups("")
        assert groups == set()

    @pytest.mark.asyncio
    async def test_load_groups_redis_error(
        self, authenticator: WSAuthenticator
    ) -> None:
        """_load_groups returns empty set on redis error."""
        with patch(
            "src.backend.core.di.providers.get_redis_kv_client_provider",
            side_effect=ImportError,
        ):
            groups = await authenticator._load_groups("hash")
        assert groups == set()

    def test_can_access_group_admin(self, authenticator: WSAuthenticator) -> None:
        """Admin can access any group."""
        session = WSSession(
            client_id="c", api_key_hash="h", allowed_groups=set(), is_admin=True
        )
        assert authenticator.can_access_group(session, "any") is True

    def test_can_access_group_member(self, authenticator: WSAuthenticator) -> None:
        """Member can access allowed group."""
        session = WSSession(
            client_id="c", api_key_hash="h", allowed_groups={"g1"}, is_admin=False
        )
        assert authenticator.can_access_group(session, "g1") is True
        assert authenticator.can_access_group(session, "g2") is False

    @pytest.mark.asyncio
    async def test_grant_group(self, authenticator: WSAuthenticator) -> None:
        """grant_group calls sadd on redis."""
        mock_redis = AsyncMock()

        with patch(
            "src.backend.core.di.providers.get_redis_kv_client_provider",
            return_value=mock_redis,
        ):
            await authenticator.grant_group("hash", "group")

        mock_redis.sadd.assert_awaited_once_with("ws:groups:hash", "group")

    @pytest.mark.asyncio
    async def test_revoke_group(self, authenticator: WSAuthenticator) -> None:
        """revoke_group calls srem on redis."""
        mock_redis = AsyncMock()

        with patch(
            "src.backend.core.di.providers.get_redis_kv_client_provider",
            return_value=mock_redis,
        ):
            await authenticator.revoke_group("hash", "group")

        mock_redis.srem.assert_awaited_once_with("ws:groups:hash", "group")


class TestGetWSAuthenticator:
    """Tests for get_ws_authenticator singleton."""

    def test_returns_same_instance(self) -> None:
        """get_ws_authenticator returns the same instance."""
        a1 = get_ws_authenticator()
        a2 = get_ws_authenticator()
        assert a1 is a2
