"""Unit-тесты для webhook dedup (cycle-22 P1-1 fix)."""

# ruff: noqa: S101

from __future__ import annotations

import time

import pytest

from src.backend.infrastructure.sources.webhook import WebhookSource


class TestDeliveryIdExtraction:
    def test_extract_github(self):
        h = {"X-GitHub-Delivery": "abc-123"}
        assert WebhookSource._extract_delivery_id(h) == "abc-123"

    def test_extract_stripe(self):
        h = {"X-Delivery-Id": "stripe-456"}
        assert WebhookSource._extract_delivery_id(h) == "stripe-456"

    def test_extract_request_id(self):
        h = {"X-Request-Id": "req-789"}
        assert WebhookSource._extract_delivery_id(h) == "req-789"

    def test_extract_missing(self):
        h = {"Content-Type": "application/json"}
        assert WebhookSource._extract_delivery_id(h) is None


class TestDedup:
    def setup_method(self):
        WebhookSource._dedup_cache.clear()

    def test_first_sight_not_duplicate(self):
        assert WebhookSource._is_duplicate("id1") is False

    def test_second_sight_is_duplicate(self):
        WebhookSource._is_duplicate("id2")
        assert WebhookSource._is_duplicate("id2") is True

    def test_different_ids_not_duplicates(self):
        WebhookSource._is_duplicate("a")
        WebhookSource._is_duplicate("b")
        assert WebhookSource._is_duplicate("a") is True
        assert WebhookSource._is_duplicate("b") is True

    def test_ttl_expiry(self):
        WebhookSource._is_duplicate("old")
        # Force-expire by manipulating cache timestamp
        for k in WebhookSource._dedup_cache:
            WebhookSource._dedup_cache[k] = time.monotonic() - 700.0
        assert WebhookSource._is_duplicate("old") is False

    def test_max_size_eviction(self):
        # Fill cache to limit
        for i in range(WebhookSource._DEDUP_MAX):
            WebhookSource._is_duplicate(f"id_{i}")
        # Add one more — should evict oldest
        WebhookSource._is_duplicate("id_new")
        assert len(WebhookSource._dedup_cache) <= WebhookSource._DEDUP_MAX
