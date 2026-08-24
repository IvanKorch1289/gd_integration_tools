"""Shared test helpers for AuthorizationFacade mocking.

S44 W4: 60+ tests fail across 13 files because ``@require_capability``
decorator on sink/source ``send`` methods fails closed when called
without a registered policy for the principal. The standard test
pattern (see ``test_connector_auth.py::test_allowed_capability_passes_through``)
mocks ``src.backend.services.authorization.facade.get_authorization_facade``
to return an ``AsyncMock`` that allows every check.

This module centralizes the mock so we don't duplicate it 60+ times.

Usage::

    from tests.unit._auth_mocks import patched_auth_allow

    async def test_sink_send():
        with (
            patch("src.backend.core.net.OutboundHttpClient", return_value=client),
            patched_auth_allow(),
        ):
            sink = WebhookSink(...)
            result = await sink.send({"id": 1})

    # OR if test needs to also pass _principal:
    with (
        patch("...OutboundHttpClient", return_value=client),
        patched_auth_allow(),
    ):
        await source.verify_and_dispatch(body, headers, _principal="webhook-service")

Architectural note (S44 W3, commit b1018f96):
    ``@require_capability`` on connector methods is defense-in-depth at
    the wrong layer. HMAC signatures ARE the auth for webhooks. Future
    refactor: move capability check to router layer (where ``require_auth``
    middleware lives) and keep HMAC validation in connector. This helper
    preserves the current contract so tests can run today.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch


def allow_capability_decision() -> MagicMock:
    """Mock decision object that allows the capability check."""
    decision = MagicMock()
    decision.allowed = True
    decision.reason = None
    return decision


def allow_capability_mock() -> AsyncMock:
    """AsyncMock для ``AuthorizationFacade.check_principal`` → allowed."""
    return AsyncMock(return_value=allow_capability_decision())


@contextmanager
def patched_auth_allow() -> Iterator[MagicMock]:
    """Context manager: mock ``get_authorization_facade`` to allow any principal.

    Returns:
        MagicMock: the mocked facade (in case test needs to inspect calls).

    Yields:
        The mocked facade inside the ``with`` block.

    Example::

        with patched_auth_allow() as facade:
            await some_connector.send(payload)
            facade.check_principal.assert_awaited()

    """
    mock_facade = MagicMock()
    mock_facade.check_principal = allow_capability_mock()
    with patch(
        "src.backend.services.authorization.facade.get_authorization_facade",
        return_value=mock_facade,
    ):
        yield mock_facade
