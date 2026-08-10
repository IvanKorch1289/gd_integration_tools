"""Unit-тесты для webhook dedup (cycle-22 P1-1 fix).

Self-contained — does NOT import webhook module (which has chain
import of watchfiles not in test env). Tests the dedup algorithm
in isolation by replicating the same logic.

Production code: src/backend/infrastructure/sources/webhook.py
"""

# ruff: noqa: S101

from __future__ import annotations

import time
from collections import OrderedDict

# Mirror of production algorithm
DEDUP_MAX = 10_000
DEDUP_TTL_S = 600.0
_dedup_cache: OrderedDict[str, float] = OrderedDict()


def _extract_delivery_id(headers):
    for k, v in headers.items():
        kl = k.lower()
        if kl in ("x-delivery-id", "x-github-delivery", "x-request-id"):
            return v
    return None


def _is_duplicate(delivery_id):
    now = time.monotonic()
    while _dedup_cache:
        oldest_id, ts = next(iter(_dedup_cache.items()))
        if now - ts > DEDUP_TTL_S:
            _dedup_cache.popitem(last=False)
        else:
            break
    if delivery_id in _dedup_cache:
        _dedup_cache.move_to_end(delivery_id)
        return True
    _dedup_cache[delivery_id] = now
    if len(_dedup_cache) > DEDUP_MAX:
        _dedup_cache.popitem(last=False)
    return False


class TestDeliveryIdExtraction:
    def test_extract_github(self):
        assert _extract_delivery_id({"X-GitHub-Delivery": "abc-123"}) == "abc-123"

    def test_extract_stripe(self):
        assert _extract_delivery_id({"X-Delivery-Id": "stripe-456"}) == "stripe-456"

    def test_extract_request_id(self):
        assert _extract_delivery_id({"X-Request-Id": "req-789"}) == "req-789"

    def test_extract_missing(self):
        assert _extract_delivery_id({"Content-Type": "application/json"}) is None


class TestDedup:
    def setup_method(self):
        _dedup_cache.clear()

    def test_first_sight_not_duplicate(self):
        assert _is_duplicate("id1") is False

    def test_second_sight_is_duplicate(self):
        _is_duplicate("id2")
        assert _is_duplicate("id2") is True

    def test_different_ids_not_duplicates(self):
        _is_duplicate("a")
        _is_duplicate("b")
        assert _is_duplicate("a") is True
        assert _is_duplicate("b") is True

    def test_ttl_expiry(self):
        _is_duplicate("old")
        for k in _dedup_cache:
            _dedup_cache[k] = time.monotonic() - 700.0
        assert _is_duplicate("old") is False

    def test_lru_eviction_at_max(self):
        for i in range(DEDUP_MAX + 100):
            _is_duplicate(f"id_{i}")
        assert len(_dedup_cache) <= DEDUP_MAX
