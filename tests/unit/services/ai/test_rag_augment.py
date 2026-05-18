"""Unit-тесты AugmentResult + FreshnessLabel (Sprint 9 K3 W4 + K4 W3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backend.services.ai.rag_augment import (
    AugmentResult,
    FreshnessLabel,
    build_augment_result,
    compute_freshness,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_compute_freshness_fresh() -> None:
    label = compute_freshness(
        ingested_at=_now() - timedelta(hours=1),
        soft_hours=72,
        hard_hours=168,
    )
    assert label is FreshnessLabel.FRESH


def test_compute_freshness_stale() -> None:
    label = compute_freshness(
        ingested_at=_now() - timedelta(hours=100),
        soft_hours=72,
        hard_hours=168,
    )
    assert label is FreshnessLabel.STALE


def test_compute_freshness_expired() -> None:
    label = compute_freshness(
        ingested_at=_now() - timedelta(hours=200),
        soft_hours=72,
        hard_hours=168,
    )
    assert label is FreshnessLabel.EXPIRED


def test_compute_freshness_none_means_expired() -> None:
    assert compute_freshness(ingested_at=None) is FreshnessLabel.EXPIRED


def test_compute_freshness_naive_datetime_treated_as_utc() -> None:
    naive = (_now() - timedelta(hours=1)).replace(tzinfo=None)
    label = compute_freshness(ingested_at=naive, soft_hours=72)
    assert label is FreshnessLabel.FRESH


def test_build_augment_result_basic() -> None:
    raw = [
        {
            "metadata": {
                "doc_id": "d1",
                "chunk_idx": 0,
                "ingested_at": (_now() - timedelta(hours=1)).isoformat(),
            },
            "score": 0.9,
            "document": "text",
        }
    ]
    result = build_augment_result(
        prompt="P", raw_results=raw, namespace="ns", top_k=5
    )
    assert result.used_results == 1
    assert result.citations[0]["doc_id"] == "d1"
    assert result.citations[0]["freshness"] == "fresh"
    assert result.worst_freshness is FreshnessLabel.FRESH


def test_build_augment_result_skips_expired_via_max_staleness() -> None:
    raw = [
        {
            "metadata": {
                "doc_id": "d-old",
                "chunk_idx": 0,
                "ingested_at": (_now() - timedelta(hours=200)).isoformat(),
            },
            "score": 0.5,
        },
        {
            "metadata": {
                "doc_id": "d-new",
                "chunk_idx": 0,
                "ingested_at": (_now() - timedelta(hours=1)).isoformat(),
            },
            "score": 0.8,
        },
    ]
    result = build_augment_result(
        prompt="P",
        raw_results=raw,
        namespace=None,
        top_k=5,
        max_staleness_hours=72.0,
    )
    assert result.used_results == 1
    assert result.skipped_expired == 1
    assert result.citations[0]["doc_id"] == "d-new"


def test_build_augment_result_tracks_distribution() -> None:
    raw = [
        {
            "metadata": {
                "doc_id": "fresh",
                "chunk_idx": 0,
                "ingested_at": (_now() - timedelta(hours=1)).isoformat(),
            }
        },
        {
            "metadata": {
                "doc_id": "stale",
                "chunk_idx": 0,
                "ingested_at": (_now() - timedelta(hours=100)).isoformat(),
            }
        },
        {
            "metadata": {
                "doc_id": "expired",
                "chunk_idx": 0,
                "ingested_at": (_now() - timedelta(hours=200)).isoformat(),
            }
        },
    ]
    result = build_augment_result(
        prompt="P", raw_results=raw, namespace=None, top_k=5
    )
    assert result.freshness_distribution["fresh"] == 1
    assert result.freshness_distribution["stale"] == 1
    assert result.freshness_distribution["expired"] == 1
    assert result.worst_freshness is FreshnessLabel.EXPIRED


def test_augment_result_to_dict() -> None:
    result = AugmentResult(prompt="P", top_k=3, namespace="ns")
    body = result.to_dict()
    assert body["prompt"] == "P"
    assert body["top_k"] == 3
    assert body["namespace"] == "ns"
    assert body["worst_freshness"] == "fresh"
