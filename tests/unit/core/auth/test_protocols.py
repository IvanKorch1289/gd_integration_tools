"""Unit tests for src.backend.core.auth.protocols."""

from __future__ import annotations

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.protocols import AuthBackend


class FakeBackend:
    method = AuthMethod.API_KEY

    async def verify(self, request: object) -> AuthContext | None:
        return None


def test_isinstance() -> None:
    assert isinstance(FakeBackend(), AuthBackend)
