"""Regression tests для lazy `__getattr__` proxy в config.services.

Per v4 §10 P1 'evidence требует testable surface': lazy proxy pattern
(cycle 158+ Option A из STARTUP_BOTTLENECK_INVESTIGATION_2026-09-23).

Pre-fix: config.services/__init__.py eager imports 15 submodules
+ 38 public symbols. Cold import = ~1.374s alone.

Post-fix: lazy __getattr__ proxy — cold import = 0.005s (~99.6% saving).

Cascade effect: config.services transitively imported через
config_loader в 47+ files, поэтому savings ripple ко всем модулям
в startup_time.py (tenancy dropped 1.326s → 0.543s etc.).
"""

from __future__ import annotations

import importlib
import sys

import pytest


def _reload():
    """Reload ``config.services`` to reset ``__getattr__`` cache.

    Per v4 §10 testable surface: lazy proxy state должен быть testable.
    """
    if "src.backend.core.config.services" in sys.modules:
        del sys.modules["src.backend.core.config.services"]
    return importlib.import_module("src.backend.core.config.services")


class TestLazyImportProxy:
    """``__getattr__`` lazy proxy pattern (PEP 562)."""

    def test_cold_import_under_50ms(self) -> None:
        """Cold import of config.services < 50ms (was 1.374s before fix).

        Per v4 §3 measurement: subprocess-based cold import must be
        significantly faster than eager baseline.
        """
        import subprocess
        import sys as _sys

        result = subprocess.run(
            [
                _sys.executable,
                "-c",
                (
                    "import time; start = time.monotonic(); "
                    "import src.backend.core.config.services; "
                    "print(f'{time.monotonic() - start:.4f}')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        elapsed = float(result.stdout.strip())

        # Pre-fix: 1.374s. Post-fix target: <50ms.
        assert elapsed < 0.05, (
            f"config.services cold import should be <50ms post-fix; got {elapsed:.3f}s"
        )

    def test_attribute_access_triggers_lazy_import(self) -> None:
        """Access triggers lazy load; identity preserved."""
        # Direct import of expected class.
        from src.backend.core.config.services.cache import (
            CacheSettings as DirectCacheSettings,
        )

        # Lazy proxy import.
        services = _reload()
        assert services.CacheSettings is DirectCacheSettings, (
            "Lazy proxy must return same class object как direct import"
        )

    def test_caching_subsequent_lookups(self) -> None:
        """Second ``getattr()`` для same name — cached."""
        services = _reload()
        first = services.CacheSettings
        second = services.CacheSettings
        assert first is second, (
            "Second lookup должен return cached value (no re-import)"
        )

    def test_unknown_attribute_raises(self) -> None:
        """``getattr(services, 'NonExistent')`` raises AttributeError."""
        services = _reload()
        with pytest.raises(AttributeError) as exc_info:
            _ = services.NonExistentClass  # noqa: F841
        assert "NonExistentClass" in str(exc_info.value)

    def test_dir_includes_all_exports(self) -> None:
        """``dir()`` proxy exposes ``__all__`` names."""
        services = _reload()
        for name in services.__all__:
            assert name in dir(services), f"dir() should include {name!r} from __all__"


class TestBackwardCompat:
    """Public contract preserved per v4 §6 «Parity»."""

    @pytest.mark.parametrize(
        "name",
        [
            # Settings classes (10)
            "CacheSettings",
            "RedisSettings",
            "GraphQLSettings",
            "InvokerSettings",
            "JupyterHubSettings",
            "LLMSettings",
            "LogStorageSettings",
            "MailSettings",
            "QueueSettings",
            "RPASettings",
            "ResilienceSettings",
            "SMSSettings",
            "SnapshotSettings",
            "FileStorageSettings",
            "WatermarkSettings",
            "WSSettings",
            "TasksSettings",
            "GRPCSettings",
            # Policy structs (2)
            "BreakerProfile",
            "FallbackPolicy",
            # Singletons (18)
            "cache_settings",
            "redis_settings",
            "graphql_settings",
            "invoker_settings",
            "jupyter_hub_settings",
            "llm_settings",
            "log_settings",
            "mail_settings",
            "queue_settings",
            "grpc_settings",
            "tasks_settings",
            "rpa_settings",
            "resilience_settings",
            "sms_settings",
            "snapshot_settings",
            "fs_settings",
            "watermark_settings",
            "ws_settings",
        ],
    )
    def test_all_exports_resolvable(self, name: str) -> None:
        """All 38 ``__all__`` entries resolvable via ``__getattr__``."""
        services = _reload()
        obj = getattr(services, name)
        assert obj is not None, f"{name} must be resolvable"


class TestTestability:
    """Indirect: оne test exercises config.services → next test sees
    sys.modules populated. Per v4 §3 evidence-first, isolation matters."""

    def test_subsequent_access_does_not_break(self) -> None:
        """Multiple consecutive accesses (warm cache path) return cached values."""
        services = _reload()
        # First access: triggers lazy import + caches.
        first = services.CacheSettings
        # Many subsequent accesses (simulating hot loop).
        for _ in range(100):
            obj = services.CacheSettings
            assert obj is first
