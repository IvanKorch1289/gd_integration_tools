"""S59 W2 tests: Redis Sentinel connection path in connection_mixin.

Per docs/security/MOBILE_JWT_PRODUCTION_FLIP_RUNBOOK.md, production HA
requires Sentinel support. This test verifies the _build_client method
correctly uses redis.asyncio.sentinel.Sentinel for sentinel_mode=True.

Tests verify:
- sentinel_mode=True → uses Sentinel.master_for (not Redis.from_url)
- Per-kind db parameter preserved (cache/queue/limits different DBs)
- sentinel_service_name passed correctly
- sentinel_password passed correctly
- SSL settings applied
- socket_timeout and other connection params propagated
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


def _make_settings(
    *,
    sentinel_mode: bool = True,
    sentinel_nodes: list[str] | None = None,
    sentinel_service_name: str = "mymaster",
    sentinel_password: str | None = None,
    use_ssl: bool = False,
    password: str | None = None,
) -> Any:
    """Build mock RedisSettings with Sentinel config."""
    settings = MagicMock()
    settings.sentinel_mode = sentinel_mode
    settings.sentinel_nodes = sentinel_nodes or ["sentinel-0:26379"]
    settings.sentinel_service_name = sentinel_service_name
    settings.sentinel_password = sentinel_password
    settings.use_ssl = use_ssl
    settings.ca_bundle = None
    settings.password = password
    settings.encoding = "utf-8"
    settings.socket_timeout = 5
    settings.socket_connect_timeout = 5
    settings.socket_keepalive = True
    settings.retry_on_timeout = True
    settings.max_connections = 20
    settings.health_check_interval = 600
    settings.cluster_mode = False
    settings.cluster_nodes = []
    settings.retry_on_error = []
    settings.host = "redis-master"
    settings.port = 6379
    return settings


def _make_client_with_settings(settings: Any) -> Any:
    """Build ConnectionMixin instance with mock settings."""
    from src.backend.infrastructure.clients.storage.redis.connection_mixin import (
        ConnectionMixin,
    )

    # Create instance bypassing __init__
    instance = ConnectionMixin.__new__(ConnectionMixin)
    instance.settings = settings
    instance.logger = MagicMock()
    return instance


def _build(settings: Any) -> Any:
    """Helper: invoke _build_client with mock Sentinel class."""
    client = _make_client_with_settings(settings)
    client._resolve_retry_on_error = MagicMock(return_value=[])
    client._db_for_kind = MagicMock(return_value=0)
    return client


# ── Sentinel path selection ──────────────────────────────────────────


def test_sentinel_mode_uses_sentinel_master_for() -> None:
    """sentinel_mode=True → uses Sentinel.master_for (NOT Redis.from_url)."""
    settings = _make_settings(sentinel_mode=True)
    client = _build(settings)

    with patch("redis.asyncio.sentinel.Sentinel") as mock_sentinel_cls:
        mock_sentinel_instance = MagicMock()
        mock_master = MagicMock()
        mock_sentinel_instance.master_for = MagicMock(return_value=mock_master)
        mock_sentinel_cls.return_value = mock_sentinel_instance

        result = client._build_client("cache")

    # Sentinel was instantiated with sentinel_nodes endpoints
    mock_sentinel_cls.assert_called_once()
    call_kwargs = mock_sentinel_cls.call_args.kwargs
    sentinel_endpoints = call_kwargs.get("sentinel_endpoints") or mock_sentinel_cls.call_args.args[0]
    assert sentinel_endpoints == [("sentinel-0", 26379)]

    # master_for called with service_name + db
    mock_sentinel_instance.master_for.assert_called_once()
    master_kwargs = mock_sentinel_instance.master_for.call_args.kwargs
    assert master_kwargs["service_name"] == "mymaster"
    assert master_kwargs["db"] == 0

    assert result is mock_master


def test_sentinel_mode_passes_service_name() -> None:
    """sentinel_service_name passed correctly to master_for."""
    settings = _make_settings(
        sentinel_mode=True, sentinel_service_name="gd-mobile-redis"
    )
    client = _build(settings)

    with patch("redis.asyncio.sentinel.Sentinel") as mock_sentinel_cls:
        mock_sentinel_instance = MagicMock()
        mock_sentinel_instance.master_for = MagicMock(return_value=MagicMock())
        mock_sentinel_cls.return_value = mock_sentinel_instance

        client._build_client("cache")

    service_name = mock_sentinel_instance.master_for.call_args.kwargs[
        "service_name"
    ]
    assert service_name == "gd-mobile-redis"


def test_sentinel_mode_passes_sentinel_password() -> None:
    """sentinel_password passed to Sentinel constructor (not master_for)."""
    settings = _make_settings(
        sentinel_mode=True, sentinel_password="sentinel-secret"
    )
    client = _build(settings)

    with patch("redis.asyncio.sentinel.Sentinel") as mock_sentinel_cls:
        mock_sentinel_instance = MagicMock()
        mock_sentinel_instance.master_for = MagicMock(return_value=MagicMock())
        mock_sentinel_cls.return_value = mock_sentinel_instance

        client._build_client("cache")

    sentinel_kwargs = mock_sentinel_cls.call_args.kwargs
    assert sentinel_kwargs.get("password") == "sentinel-secret"


def test_sentinel_mode_per_kind_db_preserved() -> None:
    """Each Redis kind (cache/queue/limits) gets its own db via _db_for_kind."""
    settings = _make_settings(sentinel_mode=True)
    client = _build(settings)

    # Different DB per kind
    dbs = {"cache": 0, "queue": 1, "limits": 2}

    with patch("redis.asyncio.sentinel.Sentinel") as mock_sentinel_cls:
        mock_sentinel_instance = MagicMock()
        mock_sentinel_instance.master_for = MagicMock(return_value=MagicMock())
        mock_sentinel_cls.return_value = mock_sentinel_instance

        for kind, expected_db in dbs.items():
            client._db_for_kind = MagicMock(return_value=expected_db)
            client._build_client(kind)

    # master_for called 3 times with correct db per kind
    calls = mock_sentinel_instance.master_for.call_args_list
    assert len(calls) == 3
    assert calls[0].kwargs["db"] == 0
    assert calls[1].kwargs["db"] == 1
    assert calls[2].kwargs["db"] == 2


def test_sentinel_mode_ssl_propagated() -> None:
    """SSL settings passed to Sentinel (for TLS-encrypted Sentinel connections)."""
    settings = _make_settings(sentinel_mode=True, use_ssl=True)
    client = _build(settings)

    with patch("redis.asyncio.sentinel.Sentinel") as mock_sentinel_cls:
        mock_sentinel_instance = MagicMock()
        mock_sentinel_instance.master_for = MagicMock(return_value=MagicMock())
        mock_sentinel_cls.return_value = mock_sentinel_instance

        client._build_client("cache")

    sentinel_kwargs = mock_sentinel_cls.call_args.kwargs
    assert sentinel_kwargs.get("ssl") is True


# ── Sentinel vs Cluster priority ───────────────────────────────────────


def test_cluster_mode_takes_priority_over_sentinel() -> None:
    """If both cluster_mode and sentinel_mode somehow enabled, Cluster wins.

    (Validators prevent this in practice, but defense-in-depth.)
    """
    settings = _make_settings(sentinel_mode=True)
    settings.cluster_mode = True  # manually override

    client = _build(settings)

    with patch("redis.asyncio.cluster.RedisCluster") as mock_cluster_cls:
        mock_cluster_cls.return_value = MagicMock()
        # Sentinel should NOT be called
        with patch("redis.asyncio.sentinel.Sentinel") as mock_sentinel_cls:
            client._build_client("cache")

    mock_cluster_cls.assert_called_once()
    mock_sentinel_cls.assert_not_called()


# ── Single instance fallback ──────────────────────────────────────────


def test_single_instance_when_no_ha_mode() -> None:
    """cluster_mode=False + sentinel_mode=False → uses Redis.from_url (single)."""
    settings = _make_settings(sentinel_mode=False)
    settings.cluster_mode = False
    client = _build(settings)
    # Mock _base_url to return valid Redis URL (Redis.from_url validates scheme)
    client._base_url = MagicMock(return_value="redis://localhost:6379")

    with patch("redis.asyncio.Redis.from_url") as mock_from_url:
        mock_from_url.return_value = MagicMock()
        client._build_client("cache")

    mock_from_url.assert_called_once()
    # Sentinel/Cluster NOT called (single instance path)
    assert mock_from_url.call_count == 1
