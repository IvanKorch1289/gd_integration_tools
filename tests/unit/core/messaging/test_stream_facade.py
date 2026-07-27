"""Runtime smoke-test for ``core.messaging.stream_facade`` lazy re-export.

The ``__all__`` symbols are resolved via PEP 562 ``__getattr__``; this test
pins the public contract guarded by ``# ruff: noqa: F822``.
"""

from __future__ import annotations

import pytest


def test_stream_facade_resolves_get_stream_client() -> None:
    """``get_stream_client`` must be reachable via attribute access."""
    from src.backend.core.messaging import stream_facade
    from src.backend.infrastructure.clients.messaging.stream import (
        get_stream_client as _infra_get_stream_client,
    )

    assert stream_facade.get_stream_client is _infra_get_stream_client


def test_stream_facade_unknown_attr_raises() -> None:
    """Unknown attrs must raise ``AttributeError`` (PEP 562 contract)."""
    from src.backend.core.messaging import stream_facade

    with pytest.raises(AttributeError):
        stream_facade.__getattr__("definitely_not_exported")


def test_stream_facade_all_contents() -> None:
    """Every symbol listed in ``__all__`` must resolve at runtime."""
    from src.backend.core.messaging import stream_facade

    for name in stream_facade.__all__:
        getattr(stream_facade, name)
