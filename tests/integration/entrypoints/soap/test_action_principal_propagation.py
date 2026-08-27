"""P0 security regression test (Cycle 5, production-grade plan).

Проверка: ``dispatch_action()`` пробросил ``principal`` / ``permissions``
в ``ActionCommandSchema.meta`` для SOAP ActionHandler path.

Pre-fix: SOAP ``_dispatch_via_action`` вызывал
``dispatch_action(action, payload, source="soap")`` без auth context.
Tier-1/2 actions, проверяющие ``cmd.meta["principal"]`` /
``cmd.meta["permissions"]``, получали пустые значения → routes с
permission checks fail-open для authorized SOAP callers.

Post-fix: ``_dispatch_via_action`` принимает ``auth=`` keyword и
пробрасывает ``principal`` / ``permissions`` через meta.

Запуск::

    .venv/bin/python -m pytest \\
      tests/integration/entrypoints/soap/test_action_principal_propagation.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.auth_context_helpers import extract_user_permissions
from src.backend.entrypoints.base import dispatch_action


@pytest.fixture
def mock_action_registry(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Mock ``action_handler_registry.dispatch`` чтобы захватить ``command``."""
    from src.backend.entrypoints import base

    captured: dict = {}

    async def fake_dispatch(command: object) -> dict:
        captured["command"] = command
        return {"ok": True}

    mock_registry = MagicMock()
    mock_registry.dispatch = AsyncMock(side_effect=fake_dispatch)
    monkeypatch.setattr(base, "action_handler_registry", mock_registry)
    return captured  # type: ignore[return-value]


def test_dispatch_action_accepts_principal_kwarg() -> None:
    """``dispatch_action`` принимает ``principal`` / ``permissions`` kwargs
    без TypeError (backward-compat: defaults — пустые значения)."""
    sig = dispatch_action.__annotations__
    assert "principal" in sig, (
        "dispatch_action НЕ имеет параметра principal (P0 cycle 5)"
    )
    assert "permissions" in sig, (
        "dispatch_action НЕ имеет параметра permissions (P0 cycle 5)"
    )


def test_dispatch_action_propagates_principal_into_meta(
    mock_action_registry: dict,
) -> None:
    """При вызове с ``principal='alice'``, ``meta.principal='alice'``."""
    asyncio.run(
        dispatch_action(
            action="test.action",
            payload={"x": 1},
            source="soap",
            principal="alice",
            permissions=("read:orders", "write:orders"),
        )
    )
    cmd = mock_action_registry["command"]
    assert cmd.meta.principal == "alice", (
        f"Expected principal='alice' in meta, got {cmd.meta.principal!r}"
    )
    assert "read:orders" in cmd.meta.permissions, (
        f"Expected permissions contain 'read:orders', got {cmd.meta.permissions!r}"
    )


def test_dispatch_action_default_principal_empty() -> None:
    """Backward-compat: без principal — meta НЕ содержит principal (по дефолту)."""
    captured: dict = {}

    async def fake_dispatch(command: object) -> dict:
        captured["command"] = command
        return {}

    from src.backend.entrypoints import base

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(
            base,
            "action_handler_registry",
            MagicMock(dispatch=AsyncMock(side_effect=fake_dispatch)),
        )
        asyncio.run(
            dispatch_action(action="test.action", payload={}, source="rest")
        )
    finally:
        monkey.undo()
    assert captured["command"].meta.principal == "", (
        "Default principal should be empty string (backward-compat)"
    )
    assert captured["command"].meta.permissions == [], (
        "Default permissions should be empty list (backward-compat)"
    )


def test_soap_dispatch_via_action_extracts_auth_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOAP _dispatch_via_action: ``auth=AuthContext`` → principal в meta."""
    from src.backend.entrypoints.soap.soap_handler import _dispatch_via_action

    auth = AuthContext(
        method=AuthMethod.JWT,
        principal="bob",
        metadata={"permissions": ["admin"]},
    )

    captured: dict = {}

    async def fake_dispatch_action(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "src.backend.entrypoints.base.dispatch_action", fake_dispatch_action
    )
    asyncio.run(
        _dispatch_via_action("test.soap_action", {"k": "v"}, auth=auth)
    )

    assert captured.get("principal") == "bob", (
        f"SOAP _dispatch_via_action НЕ пробрасывает principal. "
        f"Got: {captured.get('principal')!r}"
    )
    perms = captured.get("permissions", ())
    assert "admin" in perms, (
        f"SOAP _dispatch_via_action НЕ пробрасывает permissions. Got: {perms!r}"
    )


def test_soap_dispatch_via_action_handles_none_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed: ``auth=None`` → principal='' / permissions=() (как до fix)."""
    from src.backend.entrypoints.soap.soap_handler import _dispatch_via_action

    captured: dict = {}

    async def fake_dispatch_action(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(
        "src.backend.entrypoints.base.dispatch_action", fake_dispatch_action
    )
    asyncio.run(_dispatch_via_action("test.action", {}, auth=None))

    assert captured.get("principal") == "", (
        "auth=None should yield principal='' (fail-closed)"
    )
    assert captured.get("permissions") == ()


def test_extract_user_permissions_unchanged() -> None:
    """Sanity: extract_user_permissions всё ещё работает для AuthContext."""
    auth = AuthContext(
        method=AuthMethod.API_KEY,
        principal="carol",
        metadata={"permissions": ["read", "write"]},
    )
    perms = extract_user_permissions(auth)
    assert "read" in perms
    assert "write" in perms
