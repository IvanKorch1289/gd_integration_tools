"""Round 5 Imp.4: RAG cache metrics получили label ``version``.

Это позволяет в Grafana разделять legacy-ключи ``rag:l3:*`` от
текущих ``rag:l3:v2:*`` после cutover и видеть, есть ли вообще
legacy-нагрузка (carry-over от pre-Sprint 2.1 deployments).
"""

from __future__ import annotations


class TestMetricsVersionLabel:
    """Проверка, что ``record_hit``/``record_miss`` принимают ``version``."""

    def setup_method(self) -> None:
        """Reset singleton state между тестами (counter + snapshot)."""
        from src.backend.infrastructure.cache.rag import metrics

        metrics._initialized = False
        metrics._hits = None
        metrics._misses = None
        metrics._snapshot = {
            "hits": {"l1": 0, "l2": 0, "l3": 0},
            "misses": {"l1": 0, "l2": 0, "l3": 0},
        }

    def test_record_hit_default_version_is_v2(self) -> None:
        """Default ``version`` = ``"v2"`` (current key-scheme)."""
        from src.backend.infrastructure.cache.rag import metrics

        metrics.record_hit("l3")
        snapshot = metrics.get_metrics_snapshot()
        assert snapshot["hits"]["l3"] == 1

    def test_record_hit_explicit_legacy_version(self) -> None:
        """Legacy version (``"legacy"``) для carry-over ключей ``rag:l3:*``."""
        from src.backend.infrastructure.cache.rag import metrics

        metrics.record_hit("l3", version="legacy")
        snapshot = metrics.get_metrics_snapshot()
        # Snapshot не разделяет по version (это internal counters),
        # но сам факт вызова не должен падать.
        assert snapshot["hits"]["l3"] == 1

    def test_record_miss_default_version(self) -> None:
        """``record_miss`` тоже принимает version kwarg."""
        from src.backend.infrastructure.cache.rag import metrics

        metrics.record_miss("l2")
        snapshot = metrics.get_metrics_snapshot()
        assert snapshot["misses"]["l2"] == 1

    def test_record_miss_custom_version(self) -> None:
        """``record_miss(..., version="legacy")`` — допустимый input."""
        from src.backend.infrastructure.cache.rag import metrics

        metrics.record_miss("l2", version="legacy")
        snapshot = metrics.get_metrics_snapshot()
        assert snapshot["misses"]["l2"] == 1

    def test_default_version_constant_exists(self) -> None:
        """``DEFAULT_VERSION`` константа = ``"v2"`` (синхронизирована с PREFIX)."""
        from src.backend.infrastructure.cache.rag import metrics

        assert metrics.DEFAULT_VERSION == "v2"
        # Sanity check: PREFIX в L3RetrievalCache содержит "v2"
        from src.backend.infrastructure.cache.rag.retrieval import L3RetrievalCache

        assert "v2" in L3RetrievalCache.PREFIX


class TestBackwardCompat:
    """Проверка, что callers с positional arg не сломались."""

    def setup_method(self) -> None:
        """Reset singleton state."""
        from src.backend.infrastructure.cache.rag import metrics

        metrics._initialized = False
        metrics._hits = None
        metrics._misses = None
        metrics._snapshot = {
            "hits": {"l1": 0, "l2": 0, "l3": 0},
            "misses": {"l1": 0, "l2": 0, "l3": 0},
        }

    def test_positional_tier_arg_works(self) -> None:
        """Существующие callers ``record_hit("l1")`` не сломались."""
        from src.backend.infrastructure.cache.rag import metrics

        metrics.record_hit("l1")
        metrics.record_miss("l1")
        snapshot = metrics.get_metrics_snapshot()
        assert snapshot["hits"]["l1"] == 1
        assert snapshot["misses"]["l1"] == 1
