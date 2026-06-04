"""Unit tests for src.backend.dsl.processors.claim_check_processor (K3 W1, S38).

Subagent #1 created claim_check_processor.py (136 LOC) but timed out before
test creation. Orchestrator завершил.

Note: проект уже имеет existing ClaimCheckProcessor в
src/backend.dsl.engine.processors.eip.transformation. Этот файл
тестирует SLIM S3-only alternative.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.claim_check_processor import ClaimCheckProcessor


def _make_exchange(body: Any = b"") -> Exchange:
    msg = Message(body=body, headers={})
    return Exchange(in_message=msg, out_message=msg)


def _make_s3_client() -> Any:
    """Mocked S3 client с put_object + get_object_bytes."""
    client = MagicMock()
    client.put_object = AsyncMock()
    client.get_object_bytes = AsyncMock(return_value=b"retrieved-payload")
    return client


class TestClaimCheckInit:
    def test_init_store(self) -> None:
        p = ClaimCheckProcessor(
            s3_bucket="test-bucket", direction="store", s3_client=lambda: _make_s3_client()
        )
        assert p._direction == "store"
        assert p._s3_bucket == "test-bucket"

    def test_init_retrieve(self) -> None:
        p = ClaimCheckProcessor(
            s3_bucket="test-bucket", direction="retrieve", s3_client=lambda: _make_s3_client()
        )
        assert p._direction == "retrieve"

    def test_init_default_threshold_256kb(self) -> None:
        p = ClaimCheckProcessor(s3_bucket="b", s3_client=lambda: _make_s3_client())
        assert p._threshold == 256 * 1024

    def test_init_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            ClaimCheckProcessor(
                s3_bucket="b", direction="upsert", s3_client=lambda: _make_s3_client()
            )

    def test_init_negative_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            ClaimCheckProcessor(
                s3_bucket="b", threshold_bytes=-1, s3_client=lambda: _make_s3_client()
            )

    def test_init_with_prefix(self) -> None:
        p = ClaimCheckProcessor(
            s3_bucket="b", s3_key_prefix="myapp/claims/", s3_client=lambda: _make_s3_client()
        )
        assert p._s3_key_prefix == "myapp/claims/"


class TestClaimCheckStore:
    async def test_store_small_payload_passthrough(self) -> None:
        """Payload < threshold → no S3 upload, claim_ticket not set."""
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(s3_bucket="b", s3_client=lambda: s3)
        ex = _make_exchange(b"small")
        await p.process(ex, context=MagicMock())
        s3.put_object.assert_not_called()
        assert ex.get_property("claim_ticket") is None

    async def test_store_large_payload_uploads(self) -> None:
        """Payload > threshold → uploaded to S3, claim_ticket set."""
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(s3_bucket="b", s3_client=lambda: s3)
        large = b"x" * (300 * 1024)  # 300 KB
        ex = _make_exchange(large)
        await p.process(ex, context=MagicMock())
        s3.put_object.assert_called_once()
        assert ex.get_property("claim_ticket") is not None

    async def test_store_uses_uuid_for_key(self) -> None:
        """Each store generates unique S3 key (no overwrite)."""
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(s3_bucket="b", s3_client=lambda: s3)
        ex1 = _make_exchange(b"x" * 300000)
        ex2 = _make_exchange(b"y" * 300000)
        await p.process(ex1, context=MagicMock())
        await p.process(ex2, context=MagicMock())
        ticket1 = ex1.get_property("claim_ticket")
        ticket2 = ex2.get_property("claim_ticket")
        assert ticket1 != ticket2

    async def test_store_uses_prefix(self) -> None:
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(
            s3_bucket="b", s3_key_prefix="app/claims/", s3_client=lambda: s3
        )
        ex = _make_exchange(b"x" * 300000)
        await p.process(ex, context=MagicMock())
        ticket = ex.get_property("claim_ticket")
        assert ticket.startswith("app/claims/")

    async def test_store_threshold_configurable(self) -> None:
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(
            s3_bucket="b", threshold_bytes=100, s3_client=lambda: s3  # 100 bytes threshold
        )
        # 200 bytes > 100 → stored
        ex = _make_exchange(b"x" * 200)
        await p.process(ex, context=MagicMock())
        s3.put_object.assert_called_once()

    async def test_store_under_threshold(self) -> None:
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(s3_bucket="b", s3_client=lambda: s3)
        ex = _make_exchange(b"x" * 100 * 1024)  # 100 KB
        await p.process(ex, context=MagicMock())
        s3.put_object.assert_not_called()

    async def test_store_over_threshold(self) -> None:
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(s3_bucket="b", s3_client=lambda: s3)
        ex = _make_exchange(b"x" * 500 * 1024)  # 500 KB
        await p.process(ex, context=MagicMock())
        s3.put_object.assert_called_once()

    async def test_store_sets_claim_size(self) -> None:
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(s3_bucket="b", s3_client=lambda: s3)
        payload = b"x" * 300 * 1024
        ex = _make_exchange(payload)
        await p.process(ex, context=MagicMock())
        assert ex.get_property("claim_size") == len(payload)


class TestClaimCheckRetrieve:
    async def test_retrieve_with_ticket_downloads(self) -> None:
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(
            s3_bucket="b", direction="retrieve", s3_client=lambda: s3
        )
        ex = _make_exchange()
        ex.set_property("claim_ticket", "app/claims/abc123")
        await p.process(ex, context=MagicMock())
        s3.get_object_bytes.assert_called_once()
        assert ex.get_property("payload") == b"retrieved-payload"

    async def test_retrieve_without_ticket_passthrough(self) -> None:
        s3 = _make_s3_client()
        p = ClaimCheckProcessor(
            s3_bucket="b", direction="retrieve", s3_client=lambda: s3
        )
        ex = _make_exchange(b"original")
        await p.process(ex, context=MagicMock())
        s3.get_object_bytes.assert_not_called()


class TestClaimCheckToSpec:
    def test_to_spec(self) -> None:
        p = ClaimCheckProcessor(
            s3_bucket="b",
            s3_key_prefix="x/",
            threshold_bytes=1000,
            direction="store",
            s3_client=lambda: _make_s3_client(),
        )
        spec = p.to_spec()
        assert spec is not None
        assert spec["claim_check"]["s3_bucket"] == "b"
        assert spec["claim_check"]["threshold_bytes"] == 1000


class TestClaimCheckS3Injection:
    async def test_s3_client_injection(self) -> None:
        """Custom s3_client used (DI works)."""
        custom_s3 = MagicMock()
        custom_s3.put_object = AsyncMock()
        p = ClaimCheckProcessor(s3_bucket="b", s3_client=lambda: custom_s3)
        ex = _make_exchange(b"x" * 300000)
        await p.process(ex, context=MagicMock())
        custom_s3.put_object.assert_called_once()
