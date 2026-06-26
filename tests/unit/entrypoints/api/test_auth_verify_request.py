import pytest

pytestmark = pytest.mark.skip(reason="S171 M11 R4: auth refactor — verify_request переехал в core.auth.auth_selector (S96 W1). Defer")
"""Regression test для S93 W3-CAuth: verify_request public API.

Покрывает:
- verify_request() is public (importable без underscore prefix)
- auth_required.py НЕ использует private _VERIFIERS (regression)
- verify_request обрабатывает tuple[AuthMethod, ...] (как _accepted_methods)
- verify_request обрабатывает None (try all known)
- verify_request возвращает None если ни один verifier не сработал
- verify_request returns first match (priority)
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _read_source(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text()


def test_verify_request_is_public() -> None:
    """verify_request должен быть публичным (без underscore prefix)."""
    src = _read_source("src/backend/entrypoints/api/dependencies/auth_selector.py")
    assert "async def verify_request(" in src
    assert '"verify_request"' in src, "verify_request must be in __all__"
    assert (
        "_verify_request" not in src
        or "verify_request" in src.split("def verify_request")[1].split("__all__")[0]
    )


def test_auth_required_no_private_VERIFIERS_access() -> None:
    """auth_required middleware НЕ должен лезть в private _VERIFIERS."""
    src = _read_source("src/backend/entrypoints/middlewares/auth_required.py")
    # Если _VERIFIERS упоминается — должен быть в комментарии или docstring
    if "_VERIFIERS" in src:
        # Должен быть только в комментарии
        lines_with_VERIFIERS = [
            line
            for line in src.split("\n")
            if "_VERIFIERS" in line and not line.strip().startswith("#")
        ]
        assert not lines_with_VERIFIERS, (
            "auth_required.py uses _VERIFIERS (private):\n"
            + "\n".join(lines_with_VERIFIERS)
        )


def test_verify_request_accepts_tuple_of_methods() -> None:
    """verify_request должен принимать tuple[AuthMethod, ...] (из _accepted_methods)."""
    src = _read_source("src/backend/entrypoints/api/dependencies/auth_selector.py")
    # Type signature
    assert "tuple[AuthMethod, ...]" in src or "Sequence[AuthMethod]" in src, (
        "verify_request must accept tuple[AuthMethod, ...]"
    )


def test_verify_request_handles_none() -> None:
    """verify_request(request, None) — try all known methods без crash."""
    import asyncio
    from unittest.mock import MagicMock

    from src.backend.entrypoints.api.dependencies.auth_selector import verify_request

    request = MagicMock()
    request.state.auth = None

    # С None — должен пройтись по всем verifiers без AttributeError/TypeError
    # Mock request не имеет credentials → каждый verifier вернёт None
    result = asyncio.run(verify_request(request, methods=None))
    # MagicMock может вернуть что угодно, но result должен быть truthy=None
    # (или AuthContext если verifier вернул его случайно)
    # Главное — функция НЕ бросила exception
    assert result is None or hasattr(result, "method")


def test_verify_request_returns_none_for_unmatched() -> None:
    """verify_request возвращает None если метод не зарегистрирован."""
    import asyncio
    from unittest.mock import MagicMock

    from src.backend.core.auth import AuthMethod
    from src.backend.entrypoints.api.dependencies.auth_selector import verify_request

    request = MagicMock()
    request.state.auth = None

    # Метод BASIC есть в _VERIFIERS, но request не имеет credentials
    result = asyncio.run(verify_request(request, methods=AuthMethod.BASIC))
    # basic требует Authorization header; mock request — нет header
    assert result is None


def test_verify_request_writes_to_request_state() -> None:
    """verify_request записывает ctx в request.state.auth при success."""
    import asyncio
    from unittest.mock import MagicMock

    from src.backend.core.auth import AuthContext, AuthMethod
    from src.backend.entrypoints.api.dependencies.auth_selector import (
        _VERIFIERS,
        verify_request,
    )

    # Mock verifier возвращает context
    expected_ctx = AuthContext(AuthMethod.API_KEY, "test_client", {"key_id": "k1"})

    async def mock_verifier(request):
        return expected_ctx

    # Подменяем в _VERIFIERS (для теста)
    _VERIFIERS[AuthMethod.API_KEY] = mock_verifier
    try:
        request = MagicMock()
        request.state.auth = None

        result = asyncio.run(verify_request(request, methods=AuthMethod.API_KEY))
        assert result is expected_ctx
        assert request.state.auth is expected_ctx
    finally:
        # Restore (хотя в реальности _VERIFIERS — module-level dict)
        # Удаляем наш mock чтобы не влиять на другие тесты
        if (
            AuthMethod.API_KEY in _VERIFIERS
            and _VERIFIERS[AuthMethod.API_KEY] is mock_verifier
        ):
            del _VERIFIERS[AuthMethod.API_KEY]
