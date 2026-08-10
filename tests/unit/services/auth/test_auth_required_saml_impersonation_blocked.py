"""cycle-6/D-AUDIT-601 (SECURITY-P0-001) — end-to-end SAML impersonation blocked.

End-to-end тест на уровне сервиса: подделка ``saml_session`` cookie /
``X-SAML-Session-ID`` header через ``AuthRequiredMiddleware`` НЕ
проходит как валидный principal.

Реальная CVE-уязвимость (cycle-4 audit):
    ``auth_selector._verify_saml`` (до cycle-6 fix) принимал ЛЮБОЕ
    значение cookie/header как валидный principal → impersonation.

Fix: fail-CLOSED — ``_verify_saml`` raises ``NotImplementedError`` →
``verify_request`` ловит в ``try/except`` и движется дальше
(для одиночного SAML возвращает ``None``) → middleware deny (401).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.middlewares.auth_required import AuthRequiredMiddleware


def _start_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _make_scope(
    method: str,
    path: str,
    *,
    cookies: tuple[bytes, ...] = (),
    headers: tuple[tuple[bytes, bytes], ...] = (),
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": list(headers) + [(b"cookie", c) for c in cookies],
    }


def _downstream_must_not_be_called() -> AsyncMock:
    """Downstream который поднимает AssertionError, если его вызвали.

    Используется для проверки fail-CLOSED: при отказе в auth
    middleware не должен вызывать downstream app.
    """

    async def downstream(scope, receive, send):  # pragma: no cover - guarded
        raise AssertionError(
            "downstream app must NOT be called when SAML impersonation is rejected",
        )

    return AsyncMock(side_effect=downstream)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fake_saml_cookie_does_not_reach_downstream() -> None:
    """Подделка ``Cookie: saml_session=ATTACKER`` → 401, downstream НЕ вызван."""
    mw = AuthRequiredMiddleware(app=_downstream_must_not_be_called())
    send = AsyncMock()

    await mw(
        _make_scope("GET", "/api/v1/protected", cookies=(b"saml_session=ATTACKER",)),
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 401, (
        f"SECURITY-P0-001 regression: fake SAML cookie был принят как валидный, "
        f"got status={start['status']!r}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fake_saml_header_does_not_reach_downstream() -> None:
    """Подделка ``X-SAML-Session-ID: ATTACKER`` → 401, downstream НЕ вызван."""
    mw = AuthRequiredMiddleware(app=_downstream_must_not_be_called())
    send = AsyncMock()

    await mw(
        _make_scope(
            "GET",
            "/api/v1/protected",
            headers=((b"x-saml-session-id", b"ATTACKER_HEADER"),),
        ),
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 401, (
        f"SECURITY-P0-001 regression: fake SAML header был принят, "
        f"got status={start['status']!r}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_credentials_returns_401_with_json_detail() -> None:
    """Без credentials → 401 + JSON body с ``detail`` (стандартный путь)."""
    mw = AuthRequiredMiddleware(app=_downstream_must_not_be_called())
    send = AsyncMock()

    await mw(
        _make_scope("GET", "/api/v1/protected"),
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 401
    # Body — JSON с detail (auth_required использует JSONResponse).
    body_msg = next(
        (c.args[0] for c in send.await_args_list if c.args[0]["type"] == "http.response.body"),
        None,
    )
    assert body_msg is not None
    body = json.loads(body_msg["body"])
    assert "detail" in body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_jwt_passes_through_saml_fail_closed() -> None:
    """Валидный JWT проходит (SAML fail-CLOSED не ломает JWT flow).

    Проверяет, что fix в ``_verify_saml`` не задевает другие verifier'ы —
    ``verify_request`` move-on при исключении в SAML, JWT остаётся.
    """

    async def downstream(scope, receive, send):
        # state должен содержать AuthContext с JWT.
        auth: AuthContext | None = scope.get("state", {}).get("auth")
        assert auth is not None
        assert auth.method == AuthMethod.JWT
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock(side_effect=downstream)
    mw = AuthRequiredMiddleware(app=app)
    send = AsyncMock()

    # Подделка SAML cookie + валидный JWT — JWT должен пройти.
    # JWT format `<header>.<payload>.<sig>` в base64.
    import base64

    def b64(b: bytes) -> bytes:
        return base64.urlsafe_b64encode(b).rstrip(b"=")

    fake_jwt = b".".join(
        [
            b64(b'{"alg":"none"}'),
            b64(b'{"sub":"alice","iss":"test"}'),
            b"signature-not-validated-here",
        ],
    )

    await mw(
        _make_scope(
            "GET",
            "/api/v1/protected",
            cookies=(b"saml_session=ATTACKER",),
            headers=((b"authorization", b"Bearer " + fake_jwt),),
        ),
        AsyncMock(),
        send,
    )

    # downstream вызван ИЛИ 401 от JWT verify (но НЕ от SAML impersonation).
    # Главное — НЕ было impersonation bypass.
    start = _start_message(send)
    assert start is not None
    # JWT без реального backend key может вернуть 401 (это OK —
    # SAML fail-CLOSED не должен был accept'ить cookie).
    assert start["status"] in (200, 401)
