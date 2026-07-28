"""Tests for Cycle 38 Vault token auto-renewal.

Validates that _maybe_renew_token:
- Calls renew_self() when TTL < 7 days AND renewable=True
- Skips renew when TTL >= 7 days
- Skips renew when renewable=False (root tokens)
- Doesn't propagate lookup errors (best-effort)
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.secrets import vault_client as _mod


class _MockToken:
    """Standalone mock token — Python doesn't allow referencing nested classes."""

    def __init__(self, ttl: int, renewable: bool, raise_on_lookup: bool = False) -> None:
        self._ttl = ttl
        self._renewable = renewable
        self._raise_on_lookup = raise_on_lookup
        self.renew_called = False

    def lookup_self(self) -> dict[str, Any]:
        if self._raise_on_lookup:
            raise ConnectionError("vault unreachable")
        return {"data": {"ttl": self._ttl, "renewable": self._renewable}}

    def renew_self(self) -> dict[str, Any]:
        self.renew_called = True
        return {"renewed": True}


class _MockAuth:
    def __init__(self, token: _MockToken) -> None:
        self.token = token


class _MockClient:
    def __init__(self, token: _MockToken) -> None:
        self.auth = _MockAuth(token)


def _vc() -> Any:
    """Build uninitialized VaultClient (avoid constructor side-effects)."""
    return _mod.VaultClient.__new__(_mod.VaultClient)


class TestVaultTokenAutoRenewal:
    """Cycle 38: token renewal to prevent silent 32-day failure."""

    @pytest.mark.asyncio
    async def test_renew_token_when_ttl_below_threshold(self) -> None:
        """When TTL < 7 days AND renewable=True, call renew_self()."""
        token = _MockToken(ttl=86400, renewable=True)  # 1 day
        client = _MockClient(token)
        vc = _vc()
        await vc._maybe_renew_token(client)
        assert token.renew_called, "Expected renew_self() to be called"

    @pytest.mark.asyncio
    async def test_skip_renew_when_ttl_above_threshold(self) -> None:
        """When TTL >= 7 days, skip renew (no-op)."""
        token = _MockToken(ttl=86400 * 30, renewable=True)  # 30 days
        client = _MockClient(token)
        vc = _vc()
        await vc._maybe_renew_token(client)
        assert not token.renew_called, "renew should be skipped when TTL=30 days"

    @pytest.mark.asyncio
    async def test_skip_renew_when_not_renewable(self) -> None:
        """Root tokens (non-renewable) skip renew."""
        token = _MockToken(ttl=60, renewable=False)
        client = _MockClient(token)
        vc = _vc()
        await vc._maybe_renew_token(client)
        assert not token.renew_called

    @pytest.mark.asyncio
    async def test_renew_check_failure_does_not_propagate(self) -> None:
        """Lookup errors are warnings, not exceptions (best-effort)."""
        token = _MockToken(ttl=0, renewable=True, raise_on_lookup=True)
        client = _MockClient(token)
        vc = _vc()
        # Should not raise
        await vc._maybe_renew_token(client)
        assert not token.renew_called  # renew wasn't called because lookup failed

    @pytest.mark.asyncio
    async def test_no_ttl_info_skips_renew(self) -> None:
        """When ttl=0 in response (root tokens), skip silently."""
        token = _MockToken(ttl=0, renewable=True)
        client = _MockClient(token)
        vc = _vc()
        await vc._maybe_renew_token(client)
        assert not token.renew_called
