"""Test resolve_module fallback path для каждого provider (T-P1.2c)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.backend.core.di.providers import (
    ai,
    auth,
    cache,
    db,
    http,
    workflow,
)


def _patch_resolve_module(target_module: str) -> tuple[MagicMock, dict[str, MagicMock]]:
    """Create mock module для ``resolve_module('target_module')`` calls.

    Returns (mock_module, attr_map) — ``attr_map`` is the dict of attr_name → mock
    that will be returned when ``getattr(module, attr_name)`` is called.
    """
    mock_module = MagicMock(name=f"mock_{target_module}")
    attr_map: dict[str, MagicMock] = {}

    def getattr_handler(name: str) -> MagicMock:
        if name not in attr_map:
            attr_map[name] = MagicMock(name=f"{target_module}.{name}")
        return attr_map[name]

    mock_module.getattr = getattr_handler
    return mock_module, attr_map


class TestCacheFallbackPaths:
    def _clear_overrides(self) -> None:
        # Direct reset — set_X(None) does NOT clear override for most providers
        cache._overrides.clear()

    def test_get_cache_invalidator_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_cache_invalidator = MagicMock(return_value="fallback_invalidator")
        with patch("src.backend.core.di.providers.cache.resolve_module", return_value=mock_mod):
            result = cache.get_cache_invalidator_provider()
        assert result == "fallback_invalidator"

    def test_get_redis_kv_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_redis = MagicMock()
        mock_redis.client = "kv_client"
        mock_mod.redis_client = mock_redis
        with patch("src.backend.core.di.providers.cache.resolve_module", return_value=mock_mod):
            result = cache.get_redis_kv_client_provider()
        assert result == "kv_client"

    def test_get_admin_cache_storage_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.redis_client = "admin_storage_redis"
        with patch("src.backend.core.di.providers.cache.resolve_module", return_value=mock_mod):
            result = cache.get_admin_cache_storage_provider()
        assert result == "admin_storage_redis"


class TestDbFallbackPaths:
    def _clear_overrides(self) -> None:
        db._overrides.clear()

    def test_get_clickhouse_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_clickhouse_client = MagicMock(return_value="clickhouse_inst")
        with patch("src.backend.core.di.providers.db.resolve_module", return_value=mock_mod):
            result = db.get_clickhouse_client_provider()
        assert result == "clickhouse_inst"

    def test_get_mongo_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_mongo_client = "mongo_factory"
        with patch("src.backend.core.di.providers.db.resolve_module", return_value=mock_mod):
            result = db.get_mongo_client_provider()
        assert result == "mongo_factory"

    def test_get_connector_registry_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.ConnectorRegistry.instance = MagicMock(return_value="registry_inst")
        with patch("src.backend.core.di.providers.db.resolve_module", return_value=mock_mod):
            result = db.get_connector_registry_provider()
        assert result == "registry_inst"


class TestHttpFallbackPaths:
    def _clear_overrides(self) -> None:
        http._overrides.clear()

    def test_get_http_client_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_http_client_dependency = MagicMock(return_value="http_client_inst")
        with patch("src.backend.core.di.providers.http.resolve_module", return_value=mock_mod):
            result = http.get_http_client_provider()
        assert result == "http_client_inst"

    def test_get_smtp_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.smtp_client = "smtp_inst"
        with patch("src.backend.core.di.providers.http.resolve_module", return_value=mock_mod):
            result = http.get_smtp_client_provider()
        assert result == "smtp_inst"

    def test_get_browser_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_browser_client = MagicMock(return_value="browser_inst")
        with patch("src.backend.core.di.providers.http.resolve_module", return_value=mock_mod):
            result = http.get_browser_client_provider()
        assert result == "browser_inst"

    def test_get_redis_hash_factory_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.RedisHash = "RedisHash_class"
        with patch("src.backend.core.di.providers.http.resolve_module", return_value=mock_mod):
            result = http.get_redis_hash_factory_provider()
        assert result == "RedisHash_class"


class TestAiFallbackPaths:
    def _clear_overrides(self) -> None:
        ai._overrides.clear()

    def test_get_model_enum_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_model_enum = "model_enum_func"
        with patch("src.backend.core.di.providers.ai.resolve_module", return_value=mock_mod):
            result = ai.get_model_enum_provider()
        assert result == "model_enum_func"

    def test_get_vault_refresher_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.VaultSecretRefresher.get = MagicMock(return_value="vault_inst")
        with patch("src.backend.core.di.providers.ai.resolve_module", return_value=mock_mod):
            result = ai.get_vault_refresher_provider()
        assert result == "vault_inst"

    def test_get_antivirus_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_antivirus_service_dependency = MagicMock(return_value="av_inst")
        with patch("src.backend.core.di.providers.ai.resolve_module", return_value=mock_mod):
            result = ai.get_antivirus_service_provider()
        assert result == "av_inst"


class TestAuthFallbackPaths:
    def _clear_overrides(self) -> None:
        auth._overrides.clear()

    def test_get_api_key_manager_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_api_key_manager = MagicMock(return_value="apikey_inst")
        with patch("src.backend.core.di.providers.auth.resolve_module", return_value=mock_mod):
            result = auth.get_api_key_manager_provider()
        assert result == "apikey_inst"

    def test_build_jwks_cache_returns_none_when_no_url(self) -> None:
        from src.backend.core.config.security import secure_settings
        with patch.object(secure_settings, "jwks_url", None, create=True):
            result = auth._build_jwks_cache_or_none()
        assert result is None

    def test_build_jwks_cache_returns_instance_when_url_set(self) -> None:
        from src.backend.core.config.security import secure_settings
        with patch.object(secure_settings, "jwks_url", "https://idp.example.com/.well-known/jwks.json", create=True), \
             patch.object(secure_settings, "jwks_cache_ttl", 300, create=True), \
             patch("src.backend.core.auth.jwks_cache.JwksCache") as mock_jwks:
            mock_jwks.return_value = "jwks_cache_inst"
            result = auth._build_jwks_cache_or_none()
        assert result == "jwks_cache_inst"


class TestWorkflowFallbackPaths:
    def _clear_overrides(self) -> None:
        workflow._overrides.clear()

    def test_get_scheduler_manager_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.scheduler_manager = "scheduler_inst"
        with patch("src.backend.core.di.providers.workflow.resolve_module", return_value=mock_mod):
            result = workflow.get_scheduler_manager_provider()
        assert result == "scheduler_inst"

    def test_get_workflow_event_store_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.WorkflowEventStore = "WorkflowEventStore_class"
        with patch("src.backend.core.di.providers.workflow.resolve_module", return_value=mock_mod):
            result = workflow.get_workflow_event_store_provider()
        assert result == "WorkflowEventStore_class"

    def test_get_resilience_coordinator_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_resilience_coordinator = MagicMock(return_value="coordinator_inst")
        with patch("src.backend.core.di.providers.workflow.resolve_module", return_value=mock_mod):
            result = workflow.get_resilience_coordinator_provider()
        assert result == "coordinator_inst"

    def test_get_rate_limiter_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.get_rate_limiter = MagicMock(return_value="rate_limiter_inst")
        with patch("src.backend.core.di.providers.workflow.resolve_module", return_value=mock_mod):
            result = workflow.get_rate_limiter_provider()
        assert result == "rate_limiter_inst"

    def test_get_app_logger_falls_through(self) -> None:
        self._clear_overrides()
        mock_mod = MagicMock()
        mock_mod.app_logger = "app_logger_inst"
        with patch("src.backend.core.di.providers.workflow.resolve_module", return_value=mock_mod):
            result = workflow.get_app_logger_provider()
        assert result == "app_logger_inst"
