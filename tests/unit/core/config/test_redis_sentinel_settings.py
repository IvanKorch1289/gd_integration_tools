"""S59 W2 tests: Redis Sentinel settings (HA failover topology).

Per docs/security/MOBILE_JWT_PRODUCTION_FLIP_RUNBOOK.md + S58
S13_PHASE4_STAGING_ROLLOUT_RUNBOOK.md, production deployment requires Redis HA
infrastructure. Cluster mode (sharding) is already supported. This test
file verifies Sentinel mode (master-replica failover) configuration.

Tests verify:
- sentinel_mode field default + setter
- sentinel_nodes field with host:port format validation
- sentinel_service_name default + custom value
- sentinel_password optional
- Validators: cluster_mode + sentinel_mode mutually exclusive
- Validators: sentinel_mode=True requires non-empty sentinel_nodes
"""

from __future__ import annotations

import pytest

# ── Field defaults ─────────────────────────────────────────────────────


def test_sentinel_mode_default_off() -> None:
    """sentinel_mode defaults to False (opt-in)."""
    from src.backend.core.config.services.cache import RedisSettings

    # Build minimal valid settings (cluster off, sentinel off)
    settings = RedisSettings(
        host="localhost",
        port=6379,
        password=None,
        encoding="utf-8",
        db_cache=0,
        db_queue=1,
        db_limits=2,
        db_tasks=3,
        cache_expire_seconds=300,
        max_connections=20,
        use_ssl=False,
        max_stream_len=100000,
        approximate_trimming_stream=True,
        retention_hours_stream=24,
        max_retries=1,
        ttl_hours=1,
        health_check_interval=600,
        streams=[{"name": "main", "value": "stream1"}],
    )
    assert settings.sentinel_mode is False
    assert settings.sentinel_nodes == []
    assert settings.sentinel_service_name == "mymaster"
    assert settings.sentinel_password is None


def test_sentinel_nodes_field_accepts_host_port() -> None:
    """sentinel_nodes accepts list of host:port strings."""
    from src.backend.core.config.services.cache import RedisSettings

    settings = RedisSettings(
        host="localhost",
        port=6379,
        password=None,
        encoding="utf-8",
        db_cache=0,
        db_queue=1,
        db_limits=2,
        db_tasks=3,
        cache_expire_seconds=300,
        max_connections=20,
        use_ssl=False,
        max_stream_len=100000,
        approximate_trimming_stream=True,
        retention_hours_stream=24,
        max_retries=1,
        ttl_hours=1,
        health_check_interval=600,
        streams=[{"name": "main", "value": "stream1"}],
        sentinel_mode=True,
        sentinel_nodes=["sentinel-0:26379", "sentinel-1:26379", "sentinel-2:26379"],
        sentinel_service_name="gd-mobile-redis",
    )
    assert len(settings.sentinel_nodes) == 3
    assert "sentinel-0:26379" in settings.sentinel_nodes


# ── Validators ────────────────────────────────────────────────────────


def test_sentinel_mode_requires_non_empty_nodes() -> None:
    """sentinel_mode=True requires at least one sentinel_node."""
    from pydantic import ValidationError

    from src.backend.core.config.services.cache import RedisSettings

    with pytest.raises(ValidationError) as exc_info:
        RedisSettings(
            host="localhost",
            port=6379,
            password=None,
            encoding="utf-8",
            db_cache=0,
            db_queue=1,
            db_limits=2,
            db_tasks=3,
            cache_expire_seconds=300,
            max_connections=20,
            use_ssl=False,
            max_stream_len=100000,
            approximate_trimming_stream=True,
            retention_hours_stream=24,
            max_retries=1,
            ttl_hours=1,
            health_check_interval=600,
            streams=[{"name": "main", "value": "stream1"}],
            sentinel_mode=True,
            sentinel_nodes=[],  # empty!
        )
    assert "sentinel_nodes" in str(exc_info.value)


def test_sentinel_nodes_validates_host_port_format() -> None:
    """sentinel_nodes entries must be host:port format."""
    from pydantic import ValidationError

    from src.backend.core.config.services.cache import RedisSettings

    with pytest.raises(ValidationError):
        RedisSettings(
            host="localhost",
            port=6379,
            password=None,
            encoding="utf-8",
            db_cache=0,
            db_queue=1,
            db_limits=2,
            db_tasks=3,
            cache_expire_seconds=300,
            max_connections=20,
            use_ssl=False,
            max_stream_len=100000,
            approximate_trimming_stream=True,
            retention_hours_stream=24,
            max_retries=1,
            ttl_hours=1,
            health_check_interval=600,
            streams=[{"name": "main", "value": "stream1"}],
            sentinel_mode=True,
            sentinel_nodes=["invalid-no-port"],  # no port!
        )


def test_sentinel_nodes_validates_port_is_numeric() -> None:
    """sentinel_nodes entries must have numeric port."""
    from pydantic import ValidationError

    from src.backend.core.config.services.cache import RedisSettings

    with pytest.raises(ValidationError):
        RedisSettings(
            host="localhost",
            port=6379,
            password=None,
            encoding="utf-8",
            db_cache=0,
            db_queue=1,
            db_limits=2,
            db_tasks=3,
            cache_expire_seconds=300,
            max_connections=20,
            use_ssl=False,
            max_stream_len=100000,
            approximate_trimming_stream=True,
            retention_hours_stream=24,
            max_retries=1,
            ttl_hours=1,
            health_check_interval=600,
            streams=[{"name": "main", "value": "stream1"}],
            sentinel_mode=True,
            sentinel_nodes=["sentinel-0:not-a-port"],  # non-numeric!
        )


def test_cluster_mode_and_sentinel_mode_mutually_exclusive() -> None:
    """cluster_mode=True + sentinel_mode=True must raise."""
    from pydantic import ValidationError

    from src.backend.core.config.services.cache import RedisSettings

    with pytest.raises(ValidationError) as exc_info:
        RedisSettings(
            host="localhost",
            port=6379,
            password=None,
            encoding="utf-8",
            db_cache=0,
            db_queue=1,
            db_limits=2,
            db_tasks=3,
            cache_expire_seconds=300,
            max_connections=20,
            use_ssl=False,
            max_stream_len=100000,
            approximate_trimming_stream=True,
            retention_hours_stream=24,
            max_retries=1,
            ttl_hours=1,
            health_check_interval=600,
            streams=[{"name": "main", "value": "stream1"}],
            cluster_mode=True,
            cluster_nodes=["redis-0:6379", "redis-1:6379"],
            sentinel_mode=True,  # mutually exclusive!
            sentinel_nodes=["sentinel-0:26379"],
            sentinel_service_name="gd-mobile-redis",
        )
    assert "взаимоисключающ" in str(exc_info.value).lower() or "mutually" in str(exc_info.value).lower()


# ── Production-ready configuration example ─────────────────────────


def test_production_sentinel_config_example() -> None:
    """Typical production Sentinel config: 3 sentinels + master service name."""
    from src.backend.core.config.services.cache import RedisSettings

    settings = RedisSettings(
        host="redis-master.gd-integration.svc.cluster.local",
        port=6379,
        password="redis-secure-password",
        encoding="utf-8",
        db_cache=0,
        db_queue=1,
        db_limits=2,
        db_tasks=3,
        cache_expire_seconds=300,
        max_connections=50,
        use_ssl=True,
        ca_bundle="/etc/ssl/ca-bundle.crt",
        max_stream_len=100000,
        approximate_trimming_stream=True,
        retention_hours_stream=24,
        max_retries=1,
        ttl_hours=1,
        health_check_interval=600,
        streams=[{"name": "main", "value": "stream1"}],
        sentinel_mode=True,
        sentinel_nodes=[
            "sentinel-0.gd-integration.svc.cluster.local:26379",
            "sentinel-1.gd-integration.svc.cluster.local:26379",
            "sentinel-2.gd-integration.svc.cluster.local:26379",
        ],
        sentinel_service_name="gd-mobile-redis",
        sentinel_password="sentinel-secure-password",
    )
    assert settings.sentinel_mode is True
    assert len(settings.sentinel_nodes) == 3
    assert settings.sentinel_service_name == "gd-mobile-redis"
    assert settings.use_ssl is True
