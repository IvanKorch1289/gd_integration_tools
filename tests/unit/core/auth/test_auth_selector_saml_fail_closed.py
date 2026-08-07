"""cycle-6/D-AUDIT-601 (SECURITY-P0-001) — SAML impersonation regression.

Гарантирует, что ``_verify_saml`` в :mod:`core.auth.auth_selector` НЕ
принимает ЛЮБОЕ значение cookie ``saml_session`` / header'а
``X-SAML-Session-ID`` как валидный principal.

Реальная CVE-уязвимость (cycle-4 audit):
    ``auth_selector.py:147-167`` (до cycle-6 fix) принимал ЛЮБОЕ
    значение cookie / header и строил ``AuthContext(AuthMethod.SAML,
    principal=<attacker_value>, metadata={"session_id": <attacker_value>})``.
    Через ``AuthRequiredMiddleware`` это проходило до downstream-handler'а
    с ``principal=<attacker_value>`` — impersonation CVE.

Fix: fail-CLOSED — ``logger.error`` + ``NotImplementedError`` →
``verify_request`` ловит в ``try/except`` (move-on / None-result) →
middleware deny (401).
"""

from __future__ import annotations

import logging

import pytest

from src.backend.core.auth.auth_selector import _verify_saml, verify_request
from src.backend.core.auth import AuthMethod


class _FakeCookies:
    """Implements MutableMapping interface for ``request.cookies.get``."""

    def __init__(self, raw: str | None) -> None:
        self._data: dict[str, str] = {}
        if raw:
            # Поддержка только single-cookie case (тесты используют один
            # cookie за раз).
            if "=" in raw:
                k, _, v = raw.partition("=")
                self._data[k.strip()] = v.strip()

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._data.get(key, default)


class _FakeHeaders:
    """Case-insensitive headers stub."""

    def __init__(self, items: list[tuple[str, str]]) -> None:
        self._items = items

    def get(self, key: str, default: str | None = None) -> str | None:
        for k, v in self._items:
            if k.lower() == key.lower():
                return v
        return default


class _FakeRequest:
    """Minimal request stub для ``_verify_saml`` / ``verify_request``.

    Экспонирует ``cookies`` и ``headers`` как properties
    (как в FastAPI/Starlette).
    """

    def __init__(
        self,
        *,
        cookie: str | None = None,
        header_value: str | None = None,
    ) -> None:
        self._cookies = _FakeCookies(cookie)
        items: list[tuple[str, str]] = []
        if header_value:
            items.append(("X-SAML-Session-ID", header_value))
        self._headers = _FakeHeaders(items)

    @property
    def cookies(self) -> _FakeCookies:
        return self._cookies

    @property
    def headers(self) -> _FakeHeaders:
        return self._headers


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saml_cookie_must_be_rejected_not_authenticated() -> None:
    """Fake ``saml_session`` cookie → raises ``NotImplementedError`` (deny).

    cycle-6/D-AUDIT-601 regression: до fix'а возвращался
    ``AuthContext(AuthMethod.SAML, principal="ATTACKER", ...)``.
    После fix'а — ``NotImplementedError`` (verify_request ловит в
    try/except, не выставляет ``request.state.auth`` → middleware deny).
    """
    req = _FakeRequest(cookie="saml_session=ATTACKER_FAKE_COOKIE")
    with pytest.raises(NotImplementedError) as exc_info:
        await _verify_saml(req)  # type: ignore[arg-type]
    assert "SAML verification not yet wired" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saml_header_must_be_rejected_not_authenticated() -> None:
    """Fake ``X-SAML-Session-ID`` header → raises ``NotImplementedError``."""
    req = _FakeRequest(header_value="ATTACKER_FAKE_HEADER")
    with pytest.raises(NotImplementedError):
        await _verify_saml(req)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saml_no_cookie_no_header_returns_none() -> None:
    """Отсутствие credentials → ``None`` (unchanged behavior)."""
    req = _FakeRequest()
    result = await _verify_saml(req)  # type: ignore[arg-type]
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saml_rejection_emits_error_log(caplog: pytest.LogCaptureFixture) -> None:
    """logger.error фиксирует причину отказа (observability для SOC)."""
    req = _FakeRequest(cookie="saml_session=ATTACKER")
    with caplog.at_level(logging.ERROR, logger="src.backend.core.auth.auth_selector"):
        with pytest.raises(NotImplementedError):
            await _verify_saml(req)  # type: ignore[arg-type]
    error_records = [
        r for r in caplog.records
        if r.levelno == logging.ERROR
        and "cycle-6/D-AUDIT-601" in r.getMessage()
        and "SECURITY-P0-001" in r.getMessage()
    ]
    assert error_records, (
        "Expected logger.error с marker 'cycle-6/D-AUDIT-601 SECURITY-P0-001'"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saml_rejection_raises_not_implemented_error() -> None:
    """``_verify_saml`` явно raises ``NotImplementedError``.

    Это сигнал для extensions, что SAML verification ещё не wired
    в core auth_selector; они должны либо перейти на JWT, либо
    настроить ``SamlBackend`` напрямую.
    """
    req = _FakeRequest(cookie="saml_session=ATTACKER")
    with pytest.raises(NotImplementedError) as exc_info:
        await _verify_saml(req)  # type: ignore[arg-type]
    assert "SAML verification not yet wired" in str(exc_info.value)
    assert "use JWT instead" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_request_saml_only_returns_none_on_fake_cookie() -> None:
    """``verify_request(method=SAML)`` возвращает ``None`` при fake cookie.

    End-to-end проверка: ``AuthRequiredMiddleware`` использует
    ``verify_request`` через ``require_auth`` — здесь убеждаемся,
    что downstream middleware получит ``None`` → 401.
    """
    req = _FakeRequest(cookie="saml_session=ATTACKER_END_TO_END")
    result = await verify_request(req, methods=AuthMethod.SAML)  # type: ignore[arg-type]
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_request_saml_does_not_set_state_auth() -> None:
    """``verify_request`` НЕ выставляет ``request.state.auth`` для SAML."""
    req = _FakeRequest(cookie="saml_session=ATTACKER_STATE_LEAK")
    await verify_request(req, methods=AuthMethod.SAML)  # type: ignore[arg-type]
    # ``verify_request`` присваивает ``request.state.auth = ctx`` только
    # при ``ctx is not None``. ``_FakeRequest`` без state — fail-fast.
    assert not hasattr(req, "state") or getattr(req, "state", None) is None, (
        "request.state.auth must NOT be set when SAML verification fails"
    )