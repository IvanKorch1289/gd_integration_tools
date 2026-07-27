"""Unit-тесты для lazy __getattr__ facade re-exports (S171 F822 cleanup).

Verifies that ``cert_store_facade`` and ``pii_streaming_facade`` expose
every name from their ``__all__`` at runtime via ``__getattr__``, and
that unknown names still raise ``AttributeError``.

ponytail: self-contained, no Vault / Redis / DB.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest


class TestCertStoreFacade:
    """cert_store_facade: lazy re-export ``CertStore``."""

    def test_all_contains_cert_store(self) -> None:
        from src.backend.services.security import cert_store_facade

        assert "CertStore" in cert_store_facade.__all__

    def test_cert_store_resolved_at_runtime(self) -> None:
        from src.backend.services.security import cert_store_facade

        cls = cert_store_facade.CertStore
        assert isinstance(cls, type)
        assert cls.__name__ == "CertStore"

    def test_unknown_attribute_raises(self) -> None:
        from src.backend.services.security import cert_store_facade

        with pytest.raises(AttributeError):
            cert_store_facade.DoesNotExist  # type: ignore[attr-defined]


class TestPiiStreamingFacade:
    """pii_streaming_facade: lazy re-export ``PiiStreamPolicy`` + ``stream_filter``."""

    def test_all_contains_expected_names(self) -> None:
        from src.backend.services.security import pii_streaming_facade

        assert "PiiStreamPolicy" in pii_streaming_facade.__all__
        assert "stream_filter" in pii_streaming_facade.__all__

    def test_pii_stream_policy_resolved_at_runtime(self) -> None:
        from src.backend.services.security import pii_streaming_facade

        cls = pii_streaming_facade.PiiStreamPolicy
        assert isinstance(cls, type)
        assert cls.__name__ == "PiiStreamPolicy"

    def test_stream_filter_resolved_at_runtime(self) -> None:
        from src.backend.services.security import pii_streaming_facade

        fn = pii_streaming_facade.stream_filter
        assert callable(fn)
        assert fn.__name__ == "stream_filter"

    def test_unknown_attribute_raises(self) -> None:
        from src.backend.services.security import pii_streaming_facade

        with pytest.raises(AttributeError):
            pii_streaming_facade.DoesNotExist  # type: ignore[attr-defined]
