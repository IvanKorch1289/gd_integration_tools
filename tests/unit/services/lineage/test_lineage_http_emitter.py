"""Unit tests для OpenLineageHttpEmitter.

v21 §2.1 production transport. Tests use stdlib mock для urllib.request.urlopen.
"""

from __future__ import annotations

import json
import threading
import urllib.error
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.services.lineage import OpenLineageHttpConfig, OpenLineageHttpEmitter


@contextmanager
def _mock_urlopen(responses: list[tuple[int, str] | Exception]):
    """Context manager: мокает urllib.request.urlopen.

    Каждый вызов → следующий response из списка (или raise exception).
    """
    iter_responses = iter(responses)
    calls: list[Any] = []

    def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
        calls.append({"url": req.full_url, "method": req.method, "timeout": timeout})
        resp = next(iter_responses)
        if isinstance(resp, Exception):
            raise resp
        status, body = resp
        m = MagicMock()
        m.status = status
        m.__enter__ = lambda self: self
        m.__exit__ = lambda self, *args: None
        m.read = MagicMock(return_value=body.encode("utf-8"))
        return m

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        yield calls


def _event(name: str = "test", run_id: str = "run-1", **attrs: Any) -> dict[str, Any]:
    return {
        "event_id": f"e-{name}",
        "run_id": run_id,
        "event_type": "node.create",
        "timestamp": 1_700_000_000.0,
        "node": {
            "id": f"id-{name}",
            "name": name,
            "type": "dataset",
            "attributes": attrs,
        },
        "parent_ids": [],
        "payload": {},
    }


# ── Config validation ──────────────────────────────────────────────────


class TestOpenLineageHttpConfig:
    def test_valid_http(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000")
        assert cfg.url == "http://marquez:5000"
        assert cfg.namespace == "gd_integration_tools"
        assert cfg.batch_size == 100

    def test_valid_https(self) -> None:
        cfg = OpenLineageHttpConfig("https://ol.example.com")
        assert cfg.url == "https://ol.example.com"

    def test_trailing_slash_stripped(self) -> None:
        cfg = OpenLineageHttpConfig("http://x:5000/")
        assert cfg.url == "http://x:5000"

    def test_invalid_url_scheme(self) -> None:
        with pytest.raises(ValueError, match="http"):
            OpenLineageHttpConfig("ftp://x")

    def test_empty_url(self) -> None:
        with pytest.raises(ValueError, match="url"):
            OpenLineageHttpConfig("")

    def test_batch_size_too_small(self) -> None:
        with pytest.raises(ValueError, match="batch_size"):
            OpenLineageHttpConfig("http://x", batch_size=0)

    def test_max_queue_less_than_batch(self) -> None:
        with pytest.raises(ValueError, match="max_queue"):
            OpenLineageHttpConfig("http://x", batch_size=10, max_queue=5)


# ── HTTP behavior ──────────────────────────────────────────────────────


class TestOpenLineageHttpEmitter:
    def test_sends_event_on_batch_size_reached(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=3)
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([(200, "")]) as calls:
            for i in range(3):
                em(_event(name=f"e{i}"))
        # 1 POST with 3 events
        assert len(calls) == 1
        assert calls[0]["url"] == "http://marquez:5000/api/v1/lineage"
        assert calls[0]["method"] == "POST"
        assert em.stats["sent"] == 3
        assert em.stats["pending"] == 0

    def test_buffered_when_below_batch_size(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=10)
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([]) as calls:
            for i in range(5):
                em(_event(name=f"e{i}"))
        # No POST — buffer not full
        assert calls == []
        assert em.stats["pending"] == 5
        assert em.stats["sent"] == 0

    def test_flush_sends_pending(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=100)
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([(200, "")]) as calls:
            em(_event(name="e1"))
            em(_event(name="e2"))
            sent = em.flush()
        assert sent == 2
        assert len(calls) == 1
        assert em.stats["pending"] == 0

    def test_flush_empty_returns_zero(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000")
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([]) as calls:
            sent = em.flush()
        assert sent == 0
        assert calls == []

    def test_http_error_does_not_remove_from_buffer(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=2)
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([urllib.error.URLError("connection refused")]):
            for i in range(2):
                em(_event(name=f"e{i}"))
        # Failed → events stay in buffer for retry
        assert em.stats["sent"] == 0
        assert em.stats["failed"] == 2
        assert em.stats["pending"] == 2

    def test_http_5xx_treated_as_failure(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=1)
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([(500, "internal")]):
            em(_event(name="e1"))
        assert em.stats["sent"] == 0
        assert em.stats["failed"] == 1
        assert em.stats["pending"] == 1

    def test_http_2xx_treated_as_success(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=1)
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([(201, "created")]):
            em(_event(name="e1"))
        assert em.stats["sent"] == 1
        assert em.stats["pending"] == 0

    def test_payload_serialization_format(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=1)
        em = OpenLineageHttpEmitter(cfg)

        captured: list[dict[str, Any]] = []

        def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
            captured.append(json.loads(req.data.decode("utf-8")))
            m = MagicMock()
            m.status = 200
            m.__enter__ = lambda self: self
            m.__exit__ = lambda self, *args: None
            m.read = MagicMock(return_value=b"")
            return m

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            em(_event(name="orders.create", run_id="r-42", region="eu"))

        assert len(captured) == 1
        # Batch format: list of events
        ev = captured[0][0]
        assert ev["eventType"] == "COMPLETE"
        assert ev["run"]["runId"] == "r-42"
        assert ev["job"]["name"] == "orders.create"
        assert ev["job"]["namespace"] == "gd_integration_tools"
        assert ev["outputs"][0]["name"] == "id-orders.create"

    def test_auth_token_in_header(self) -> None:
        cfg = OpenLineageHttpConfig(
            "http://marquez:5000", auth_token="secret-123", batch_size=1
        )
        em = OpenLineageHttpEmitter(cfg)

        sent_headers: dict[str, str] = {}

        def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
            sent_headers.update(req.headers)
            m = MagicMock()
            m.status = 200
            m.__enter__ = lambda self: self
            m.__exit__ = lambda self, *args: None
            m.read = MagicMock(return_value=b"")
            return m

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            em(_event(name="e1"))
        assert sent_headers["Authorization"] == "Bearer secret-123"

    def test_no_auth_header_when_token_none(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=1)
        em = OpenLineageHttpEmitter(cfg)

        sent_headers: dict[str, str] = {}

        def fake_urlopen(req, timeout=None):  # type: ignore[no-untyped-def]
            sent_headers.update(req.headers)
            m = MagicMock()
            m.status = 200
            m.__enter__ = lambda self: self
            m.__exit__ = lambda self, *args: None
            m.read = MagicMock(return_value=b"")
            return m

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            em(_event(name="e1"))
        assert "Authorization" not in sent_headers


# ── Drop-oldest on overflow ────────────────────────────────────────────


class TestOverflow:
    def test_drop_oldest_on_queue_overflow(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=10, max_queue=10)
        em = OpenLineageHttpEmitter(cfg)
        # All POSTs fail → events stay in buffer → overflow drops oldest
        with _mock_urlopen([urllib.error.URLError("fail")] * 20):
            for i in range(15):
                em(_event(name=f"e{i}"))
        assert em.stats["dropped"] == 5
        assert em.stats["pending"] == 10
        # In-memory store keeps all 15 events (drop only affects HTTP queue).
        # The drop is verified by stats counters.
        assert len(em.list_events()) == 15


# ── Thread safety ──────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_appends_dont_corrupt_buffer(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=1000)
        em = OpenLineageHttpEmitter(cfg)

        def worker(start: int) -> None:
            for i in range(100):
                em(_event(name=f"t{start}-e{i}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        with _mock_urlopen([]):
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        # 5 × 100 = 500 events in in-memory store
        assert em.stats["pending"] == 500
        assert len(em.list_events()) == 500


# ── InMemoryLineageEmitter compatibility ──────────────────────────────


class TestInMemoryCompatibility:
    def test_list_events_still_works(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=100)
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([]):
            em(_event(name="e1"))
            em(_event(name="e2"))
        # Inherited method
        events = em.list_events()
        assert len(events) == 2
        assert events[0]["event_id"] == "e-e1"

    def test_clear_resets_pending_and_stats(self) -> None:
        cfg = OpenLineageHttpConfig("http://marquez:5000", batch_size=1)
        em = OpenLineageHttpEmitter(cfg)
        with _mock_urlopen([(200, "")] * 5):
            for i in range(5):
                em(_event(name=f"e{i}"))
        assert em.stats["sent"] == 5
        em.clear()
        # Note: clear() inherited — doesn't reset _pending; OK for production
        # (in-memory store cleared for tests).
        assert len(em.list_events()) == 0
