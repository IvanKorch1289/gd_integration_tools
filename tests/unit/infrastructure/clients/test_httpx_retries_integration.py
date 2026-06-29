"""TDD: httpx-retries integration (S171 M27-P1-2, D286).

Pattern (D286, Ponytail): thin wrapper над httpx + httpx_retries.
Replace custom retry logic в HTTP-клиентах.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestHttpxRetriesIntegration:
    def test_httpx_retries_importable(self) -> None:
        """httpx_retries (retry_on_exceptions) — должен быть доступен."""
        from httpx_retries import Retry, RetryTransport
        assert Retry is not None
        assert RetryTransport is not None

    def test_retry_transport_configured(self) -> None:
        from httpx import Client
        from httpx_retries import Retry, RetryTransport
        retry = Retry(total=3, backoff_factor=0.5)
        transport = RetryTransport(retry=retry)
        client = Client(transport=transport)
        # Verify client создан с retry transport
        assert client is not None
        assert client._transport is not None
