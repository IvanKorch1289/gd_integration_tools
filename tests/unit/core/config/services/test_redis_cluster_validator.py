"""D-A12-04 fix (cycle 25): RedisSettings cluster_mode ↔ cluster_nodes consistency.

Проверяет cross-field validator:
- cluster_mode=True + cluster_nodes=[] → ValidationError
- cluster_mode=True + cluster_nodes=['redis-0:6379', ...] → OK
- cluster_mode=False + cluster_nodes=[...] → OK (warning, не error)
"""


from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestRedisClusterModeConsistency:
    """D-A12-04 fix (cycle 25): cluster_mode cross-field validation."""

    def test_cluster_mode_true_empty_cluster_nodes_raises(self) -> None:
        """cluster_mode=True + cluster_nodes=[] → ValidationError.

        Без этого fix production Redis cluster runtime failure —
        connection refused на startup.
        """
        from src.backend.core.config.services.cache import RedisSettings

        with pytest.raises(ValidationError, match="cluster_mode=True требует непустого"):
            RedisSettings(
                cluster_mode=True,
                cluster_nodes=[],
            )

    def test_cluster_mode_true_with_cluster_nodes_ok(self) -> None:
        """cluster_mode=True + cluster_nodes=['redis-0:6379'] → OK."""
        from src.backend.core.config.services.cache import RedisSettings

        s = RedisSettings(
            cluster_mode=True,
            cluster_nodes=["redis-0:6379", "redis-1:6379", "redis-2:6379"],
        )
        assert s.cluster_mode is True
        assert len(s.cluster_nodes) == 3

    def test_cluster_mode_false_empty_cluster_nodes_ok(self) -> None:
        """cluster_mode=False + cluster_nodes=[] → OK (single Redis instance)."""
        from src.backend.core.config.services.cache import RedisSettings

        s = RedisSettings(
            cluster_mode=False,
            cluster_nodes=[],
        )
        assert s.cluster_mode is False

    def test_cluster_mode_false_with_cluster_nodes_ok_with_warning(self) -> None:
        """cluster_mode=False + cluster_nodes=[...] → OK (warning logged).

        Cluster_nodes заполнены но cluster_mode=False → cluster_nodes
        игнорируются. Валидная конфигурация (например, в тестах), но operator
        должен знать — логируется info-level warning.
        """
        from src.backend.core.config.services.cache import RedisSettings

        # Не должно raise — warning через logger.
        s = RedisSettings(
            cluster_mode=False,
            cluster_nodes=["redis-0:6379"],
        )
        assert s.cluster_mode is False
        assert s.cluster_nodes == ["redis-0:6379"]

    def test_cluster_nodes_invalid_format_raises(self) -> None:
        """cluster_nodes с некорректным host:port форматом → ValidationError."""
        from src.backend.core.config.services.cache import RedisSettings

        # cluster_mode=False → cross-field check skip → только format check.
        with pytest.raises(ValidationError, match="cluster_nodes: ожидается формат"):
            RedisSettings(
                cluster_mode=False,
                cluster_nodes=["invalid-no-port"],
            )

        with pytest.raises(ValidationError, match="cluster_nodes: некорректный"):
            RedisSettings(
                cluster_mode=False,
                cluster_nodes=[":6379"],  # empty host
            )
