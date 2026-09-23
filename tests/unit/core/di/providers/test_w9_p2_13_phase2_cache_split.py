"""Focused tests: W9 P2-13 Phase 2 cache.py god-module split + re-exports.

Проверяет:
1. Cache canonical concerns остались inline в cache.py (cache_invalidator,
   admin_cache_storage, response_cache, rag_cache, redis_*).
2. Misattributed providers перенесены в proper domain modules
   (observability/security/messaging/db/ai/workflow/http).
3. Back-compat: cache.py re-exports продолжают работать для всех 89 providers.
4. Per-domain _overrides isolation: разные domain модули имеют РАЗНЫЕ
   _overrides dict'ы — set через cache.py делегирует в proper domain.
5. Top-level imports (from src.backend.core.di.providers import X) работают.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.backend.core.di import providers as providers_pkg
from src.backend.core.di.providers import ai as ai_mod
from src.backend.core.di.providers import cache as cache_mod
from src.backend.core.di.providers import db as db_mod
from src.backend.core.di.providers import http as http_mod
from src.backend.core.di.providers import messaging as messaging_mod
from src.backend.core.di.providers import observability as observability_mod
from src.backend.core.di.providers import security as security_mod
from src.backend.core.di.providers import workflow as workflow_mod


class TestCacheCanonicalConcerns:
    """Cache-only providers остались inline в cache.py."""

    def test_cache_invalidator_inline(self) -> None:
        """cache_invalidator canonical в cache.py."""
        assert cache_mod.get_cache_invalidator_provider.__module__ == (
            "src.backend.core.di.providers.cache"
        )

    def test_admin_cache_storage_inline(self) -> None:
        assert cache_mod.get_admin_cache_storage_provider.__module__ == (
            "src.backend.core.di.providers.cache"
        )

    def test_response_cache_inline(self) -> None:
        assert cache_mod.get_response_cache_provider.__module__ == (
            "src.backend.core.di.providers.cache"
        )

    def test_rag_cache_inline(self) -> None:
        assert cache_mod.get_rag_cache_provider.__module__ == (
            "src.backend.core.di.providers.cache"
        )

    def test_redis_kv_inline(self) -> None:
        assert cache_mod.get_redis_kv_client_provider.__module__ == (
            "src.backend.core.di.providers.cache"
        )

    def test_redis_lock_inline(self) -> None:
        """redis_lock_class — canonical cache concern (Redis coordination)."""
        assert cache_mod.get_redis_lock_class_provider.__module__ == (
            "src.backend.core.di.providers.cache"
        )


class TestMovedProviders:
    """Misattributed providers перенесены в proper domain modules."""

    def test_slo_tracker_in_observability(self) -> None:
        assert cache_mod.get_slo_tracker_provider.__module__ == (
            "src.backend.core.di.providers.observability"
        )

    def test_health_aggregator_in_observability(self) -> None:
        assert cache_mod.get_health_aggregator_provider.__module__ == (
            "src.backend.core.di.providers.observability"
        )

    def test_signature_builder_in_security(self) -> None:
        assert cache_mod.get_signature_builder_provider.__module__ == (
            "src.backend.core.di.providers.security"
        )

    def test_vault_backend_in_security(self) -> None:
        assert cache_mod.get_vault_backend_class_provider.__module__ == (
            "src.backend.core.di.providers.security"
        )

    def test_antivirus_in_security(self) -> None:
        assert cache_mod.get_antivirus_backend_factory_provider.__module__ == (
            "src.backend.core.di.providers.security"
        )

    def test_db_manager_in_db(self) -> None:
        assert cache_mod.get_db_manager_provider.__module__ == (
            "src.backend.core.di.providers.db"
        )

    def test_httpx_client_in_http(self) -> None:
        assert cache_mod.get_httpx_client_provider.__module__ == (
            "src.backend.core.di.providers.http"
        )

    def test_telegram_bot_in_messaging(self) -> None:
        assert cache_mod.get_telegram_bot_provider.__module__ == (
            "src.backend.core.di.providers.messaging"
        )

    def test_express_bot_in_messaging(self) -> None:
        assert cache_mod.get_express_bot_module_provider.__module__ == (
            "src.backend.core.di.providers.messaging"
        )

    def test_vector_store_in_ai(self) -> None:
        assert cache_mod.get_vector_store_provider.__module__ == (
            "src.backend.core.di.providers.ai"
        )

    def test_token_registry_in_ai(self) -> None:
        assert cache_mod.get_token_registry_provider.__module__ == (
            "src.backend.core.di.providers.ai"
        )

    def test_sink_factory_in_workflow(self) -> None:
        assert cache_mod.get_sink_factory_provider.__module__ == (
            "src.backend.core.di.providers.workflow"
        )

    def test_dlq_envelope_in_workflow(self) -> None:
        assert cache_mod.get_dlq_envelope_class_provider.__module__ == (
            "src.backend.core.di.providers.workflow"
        )


class TestBackCompatOverideIsolation:
    """Re-exports в cache.py делегируют в proper domain; _overrides isolation."""

    def test_set_through_cache_delegates_to_observability(self) -> None:
        """cache.set_slo_tracker → observability._overrides."""
        sentinel = MagicMock(name="slo_sentinel")
        cache_mod.set_slo_tracker_provider(sentinel)
        assert observability_mod.get_slo_tracker_provider() is sentinel
        assert cache_mod.get_slo_tracker_provider() is sentinel

    def test_set_through_cache_delegates_to_security(self) -> None:
        sentinel = MagicMock(name="security_sentinel")
        cache_mod.set_signature_builder_provider(sentinel)
        assert security_mod.get_signature_builder_provider() is sentinel

    def test_set_through_cache_delegates_to_db(self) -> None:
        sentinel = MagicMock(name="db_sentinel")
        cache_mod.set_db_manager_provider(sentinel)
        assert db_mod.get_db_manager_provider() is sentinel

    def test_per_domain_overrides_isolated(self) -> None:
        """Каждый domain имеет свой _overrides dict (per isolation pattern)."""
        sentinel_a = MagicMock(name="A")
        sentinel_b = MagicMock(name="B")
        cache_mod.set_cache_invalidator_provider(sentinel_a)  # cache._overrides
        cache_mod.set_slo_tracker_provider(sentinel_b)  # observability._overrides
        # Cross-domain isolation
        assert cache_mod.get_cache_invalidator_provider() is sentinel_a
        assert cache_mod.get_slo_tracker_provider() is sentinel_b
        # Direct module access works
        assert observability_mod.get_slo_tracker_provider() is sentinel_b


class TestTopLevelImports:
    """from src.backend.core.di.providers import get_X_provider работает."""

    def test_slo_tracker_top_level(self) -> None:
        assert hasattr(providers_pkg, "get_slo_tracker_provider")

    def test_signature_builder_top_level(self) -> None:
        assert hasattr(providers_pkg, "get_signature_builder_provider")

    def test_dlq_envelope_top_level(self) -> None:
        assert hasattr(providers_pkg, "get_dlq_envelope_class_provider")

    def test_telegram_bot_top_level(self) -> None:
        assert hasattr(providers_pkg, "get_telegram_bot_provider")

    def test_db_manager_top_level(self) -> None:
        assert hasattr(providers_pkg, "get_db_manager_provider")

    def test_observability_submodule_exported(self) -> None:
        """observability module exposed via providers_pkg."""
        assert hasattr(providers_pkg, "observability")

    def test_security_submodule_exported(self) -> None:
        assert hasattr(providers_pkg, "security")

    def test_messaging_submodule_exported(self) -> None:
        assert hasattr(providers_pkg, "messaging")


class TestDomainExportsCoherence:
    """Каждый domain module имеет полный __all__ со своими функциями."""

    def test_observability_all(self) -> None:
        expected = {
            "get_health_aggregator_provider",
            "get_immutable_audit_store_class_provider",
            "get_record_antivirus_scan_provider",
            "get_record_express_message_sent_provider",
            "get_slo_tracker_provider",
            "set_health_aggregator_provider",
            "set_immutable_audit_store_class_provider",
            "set_record_antivirus_scan_provider",
            "set_record_express_message_sent_provider",
            "set_slo_tracker_provider",
        }
        assert set(observability_mod.__all__) == expected

    def test_security_all(self) -> None:
        expected = {
            "get_antivirus_backend_factory_provider",
            "get_signature_builder_provider",
            "get_vault_backend_class_provider",
            "get_vault_config_class_provider",
            "set_antivirus_backend_factory_provider",
            "set_signature_builder_provider",
            "set_vault_backend_class_provider",
            "set_vault_config_class_provider",
        }
        assert set(security_mod.__all__) == expected

    def test_messaging_all(self) -> None:
        expected = {
            "get_express_bot_module_provider",
            "get_express_dialogs_mongo_provider",
            "get_telegram_bot_provider",
            "set_express_bot_module_provider",
            "set_express_dialogs_mongo_provider",
            "set_telegram_bot_provider",
        }
        assert set(messaging_mod.__all__) == expected


class TestCacheShimReduction:
    """cache.py сократился (top-2 god-module → thin shim)."""

    def test_cache_under_500_loc(self) -> None:
        """cache.py должен быть < 500 LOC после split (было 868, target <500)."""
        from pathlib import Path

        cache_path = Path(cache_mod.__file__)
        loc = sum(1 for _ in cache_path.open()) if cache_path.exists() else 0
        assert loc < 500, f"cache.py всё ещё {loc} LOC (target: <500)"

    def test_cache_inline_count(self) -> None:
        """cache.py должен содержать только cache-concern inline defs (~17)."""
        import ast

        tree = ast.parse(open(cache_mod.__file__).read())
        funcs = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and not node.name.startswith("__")
        ]
        # ~17 inline funcs (8 cache canonical get_/set_ pairs + get_cache_facade)
        assert 14 <= len(funcs) <= 25, (
            f"cache.py имеет {len(funcs)} функций, "
            f"ожидалось 14-25 (8 cache + utility + re-exports)"
        )
