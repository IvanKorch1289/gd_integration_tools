"""Focused tests for metrics (PERF-6.6 Sprint 22 coverage ratchet).

Coverage target: metrics.py → 70%+.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.observability.metrics import (
    get_dsl_metrics,
    record_pipeline_execution,
    record_pool_metric,
    record_cache_hit,
    record_cache_miss,
    record_express_message_sent,
    record_express_command_received,
    record_express_delivery_latency,
    record_ai_token_usage,
    record_ai_semantic_cache_hit,
    record_ai_semantic_cache_miss,
    record_antivirus_scan,
    record_antivirus_cache_hit,
    record_antivirus_cache_miss,
    record_queue_consumer_lag,
    record_queue_dlq_depth,
)


def test_get_dsl_metrics_returns_dict() -> None:
    """get_dsl_metrics() returns dict[str, Any]."""
    metrics = get_dsl_metrics()
    assert isinstance(metrics, dict)


def test_record_pipeline_execution_ok() -> None:
    """record_pipeline_execution с status='ok'."""
    record_pipeline_execution(route_id="test-route", status="ok")


def test_record_pipeline_execution_error() -> None:
    """record_pipeline_execution с status='error'."""
    record_pipeline_execution(route_id="test-route-2", status="error")


def test_record_pool_metric_size() -> None:
    """record_pool_metric для размера."""
    record_pool_metric(pool_name="p1", metric="size", value=5.0)


def test_record_pool_metric_in_use() -> None:
    """record_pool_metric для in_use."""
    record_pool_metric(pool_name="p1", metric="in_use", value=3.0)


def test_record_cache_hit() -> None:
    """record_cache_hit без args (defaults)."""
    record_cache_hit(backend="redis")


def test_record_cache_hit_with_key_prefix() -> None:
    """record_cache_hit с key_prefix."""
    record_cache_hit(backend="memory", key_prefix="session:")


def test_record_cache_miss() -> None:
    """record_cache_miss."""
    record_cache_miss(backend="memory")


def test_record_express_message_sent_ok() -> None:
    """record_express_message_sent с status=ok."""
    record_express_message_sent(bot="b1", status="ok")


def test_record_express_message_sent_failed() -> None:
    """record_express_message_sent с status=failed."""
    record_express_message_sent(bot="b1", status="failed")


def test_record_express_command_received() -> None:
    """record_express_command_received."""
    record_express_command_received(bot="b1", command="click")


def test_record_express_delivery_latency() -> None:
    """record_express_delivery_latency."""
    record_express_delivery_latency(bot="b1", latency_seconds=0.5)


def test_record_ai_token_usage_prompt() -> None:
    """record_ai_token_usage kind=prompt."""
    record_ai_token_usage(provider="openai", model="gpt-4", kind="prompt", tokens=100)


def test_record_ai_token_usage_completion() -> None:
    """record_ai_token_usage kind=completion."""
    record_ai_token_usage(provider="openai", model="gpt-4", kind="completion", tokens=200)


def test_record_ai_semantic_cache_hit() -> None:
    """record_ai_semantic_cache_hit."""
    record_ai_semantic_cache_hit(model="bge-small")


def test_record_ai_semantic_cache_miss() -> None:
    """record_ai_semantic_cache_miss."""
    record_ai_semantic_cache_miss(model="bge-small")


def test_record_antivirus_scan() -> None:
    """record_antivirus_scan."""
    record_antivirus_scan(backend="clamav", duration_seconds=0.1)


def test_record_antivirus_cache_hit() -> None:
    """record_antivirus_cache_hit."""
    record_antivirus_cache_hit()


def test_record_antivirus_cache_miss() -> None:
    """record_antivirus_cache_miss."""
    record_antivirus_cache_miss()


def test_record_queue_consumer_lag() -> None:
    """record_queue_consumer_lag."""
    record_queue_consumer_lag(queue="q1", consumer_group="g1", lag=10)


def test_record_queue_dlq_depth() -> None:
    """record_queue_dlq_depth."""
    record_queue_dlq_depth(queue="q1", depth=5)


def test_record_pipeline_execution_no_exception() -> None:
    """record_pipeline_execution с empty status."""
    record_pipeline_execution(route_id="r1", status="")
