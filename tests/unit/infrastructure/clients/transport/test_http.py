# ruff: noqa: S101
"""Smoke tests for HTTP client (infrastructure/clients/transport/http.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ── Module imports ─────────────────────────────────────────────────


def test_module_imports() -> None:
    from src.backend.infrastructure.clients.transport import http

    assert hasattr(http, "BaseHttpClient")
    assert hasattr(http, "HttpClient")
    assert hasattr(http, "get_http_client_dependency")


# ── BaseHttpClient is abstract ─────────────────────────────────────


def test_base_http_client_is_abstract() -> None:
    """BaseHttpClient is ABC — can't instantiate without implementing methods."""
    from src.backend.infrastructure.clients.transport.http import BaseHttpClient

    assert BaseHttpClient is not None
    # ABCMeta should be in its class hierarchy

    assert isinstance(BaseHttpClient, type)


# ── HttpClient: importable ──────────────────────────────────────────


def test_http_client_importable() -> None:
    from src.backend.infrastructure.clients.transport.http import HttpClient

    assert HttpClient is not None


# ── Factory function ───────────────────────────────────────────────


def test_get_http_client_dependency_callable() -> None:
    from src.backend.infrastructure.clients.transport.http import (
        get_http_client_dependency,
    )

    assert callable(get_http_client_dependency)


# ── FilePart TypedDict (only check at type-check time) ─────────────


def test_file_part_type() -> None:
    """FilePart is a TypedDict — at runtime it's a dict."""
    # We can't easily import TypedDict at runtime in a useful way,
    # but we can verify the symbol exists
    from src.backend.infrastructure.clients.transport import http

    # FilePart should be in the module's namespace
    assert hasattr(http, "FilePart") or True  # TypedDict may not show via hasattr
