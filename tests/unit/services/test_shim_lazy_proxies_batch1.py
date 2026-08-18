"""TDD characterization tests для Sprint 224 Candidates #2-#6 (5 re-export shims).

BEFORE refactor — verify current behavior:
- Symbol identity preserved (proxy returns original)
- Public API stable
- Lazy: infrastructure import only at first __getattr__
"""

from __future__ import annotations

import pytest


class TestCacheMetricsShimProxy:
    """Candidate #2: services/cache/metrics.py — 2 symbols."""

    def test_module_imports(self) -> None:
        from src.backend.services.cache import metrics

        assert hasattr(metrics, "__all__")

    def test_all_exports(self) -> None:
        from src.backend.services.cache.metrics import __all__

        assert set(__all__) == {"get_cache_metrics_snapshot", "get_metrics_snapshot"}

    def test_get_cache_metrics_snapshot_identity(self) -> None:
        from src.backend.services.cache.metrics import get_cache_metrics_snapshot
        from src.backend.infrastructure.cache.metrics_collector import (
            get_cache_metrics_snapshot as _orig,
        )

        assert get_cache_metrics_snapshot is _orig

    def test_get_metrics_snapshot_identity(self) -> None:
        from src.backend.services.cache.metrics import get_metrics_snapshot
        from src.backend.infrastructure.cache.rag.metrics import (
            get_metrics_snapshot as _orig,
        )

        assert get_metrics_snapshot is _orig

    def test_unknown_attribute_raises(self) -> None:
        from src.backend.services.cache import metrics

        with pytest.raises(AttributeError):
            _ = metrics.__getattr__("nonexistent_symbol_xyz")


class TestClickHouseAdminShimProxy:
    """Candidate #3: services/admin/clickhouse_admin.py — 2 symbols."""

    def test_all_exports(self) -> None:
        from src.backend.services.admin.clickhouse_admin import __all__

        assert set(__all__) == {"AdminClickHouseClient", "get_admin_clickhouse_client"}

    def test_admin_clickhouse_client_identity(self) -> None:
        from src.backend.services.admin.clickhouse_admin import AdminClickHouseClient
        from src.backend.infrastructure.clients.storage.clickhouse_admin_client import (
            AdminClickHouseClient as _orig,
        )

        assert AdminClickHouseClient is _orig

    def test_get_admin_clickhouse_client_identity(self) -> None:
        from src.backend.services.admin.clickhouse_admin import get_admin_clickhouse_client
        from src.backend.infrastructure.clients.storage.clickhouse_admin_client import (
            get_admin_clickhouse_client as _orig,
        )

        assert get_admin_clickhouse_client is _orig


class TestResilienceRateLimiterShimProxy:
    """Candidate #4: services/resilience/rate_limiter.py — 3 symbols."""

    def test_all_exports(self) -> None:
        from src.backend.services.resilience.rate_limiter import __all__

        assert set(__all__) == {"RateLimit", "RateLimitExceeded", "get_rate_limiter"}

    def test_rate_limit_identity(self) -> None:
        from src.backend.services.resilience.rate_limiter import RateLimit
        from src.backend.infrastructure.resilience.unified_rate_limiter import (
            RateLimit as _orig,
        )

        assert RateLimit is _orig

    def test_rate_limit_exceeded_identity(self) -> None:
        from src.backend.services.resilience.rate_limiter import RateLimitExceeded
        from src.backend.infrastructure.resilience.unified_rate_limiter import (
            RateLimitExceeded as _orig,
        )

        assert RateLimitExceeded is _orig

    def test_get_rate_limiter_callable(self) -> None:
        from src.backend.services.resilience.rate_limiter import get_rate_limiter

        assert callable(get_rate_limiter)


class TestWorkflowShimProxy:
    """Candidate #5: services/workflow/__init__.py — 2 symbols."""

    def test_all_exports(self) -> None:
        from src.backend.services.workflow import __all__

        assert set(__all__) == {"WorkflowDescriptor", "workflow_registry"}

    def test_workflow_descriptor_identity(self) -> None:
        from src.backend.services.workflow import WorkflowDescriptor
        from src.backend.infrastructure.workflow.registry import (
            WorkflowDescriptor as _orig,
        )

        assert WorkflowDescriptor is _orig

    def test_workflow_registry_identity(self) -> None:
        from src.backend.services.workflow import workflow_registry
        from src.backend.infrastructure.workflow.registry import (
            workflow_registry as _orig,
        )

        assert workflow_registry is _orig


class TestSchedulerAdminShimProxy:
    """Candidate #6: services/scheduler/admin.py — 3 symbols."""

    def test_all_exports(self) -> None:
        from src.backend.services.scheduler.admin import __all__

        assert set(__all__) == {
            "SchedulerDLQStore",
            "get_scheduler_dlq_store",
            "get_scheduler_manager",
        }

    def test_scheduler_dlq_store_identity(self) -> None:
        from src.backend.services.scheduler.admin import SchedulerDLQStore
        from src.backend.infrastructure.scheduler.dlq import (
            SchedulerDLQStore as _orig,
        )

        assert SchedulerDLQStore is _orig

    def test_get_scheduler_dlq_store_identity(self) -> None:
        from src.backend.services.scheduler.admin import get_scheduler_dlq_store
        from src.backend.infrastructure.scheduler.dlq import (
            get_scheduler_dlq_store as _orig,
        )

        assert get_scheduler_dlq_store is _orig

    def test_get_scheduler_manager_callable(self) -> None:
        from src.backend.services.scheduler.admin import get_scheduler_manager

        assert callable(get_scheduler_manager)