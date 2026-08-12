"""Regression-test: ``UnifiedRateLimiter`` facade removal (D-AUDIT-9601 follow-up).

Background:
    ``src/backend/core/resilience/unified_rate_limiter.py`` (S174 scaffold)
    определял ``UnifiedRateLimiter`` + ``RateLimitResult`` + ``get_unified_rate_limiter``.
    Facade НЕ имел production callsites (verified: 0 import-callsites в
    ``src/``/``extensions/``/``tests/`` за пределами собственного модуля).
    Содержал критичный security footgun: ``UnifiedRateLimiter.check()``
    catch-all ``except Exception`` → возвращает ``allowed=True`` (fail-OPEN).
    Удалён 2026-08-12 (D-AUDIT-9601 follow-up).

Goal of this test:
    Гарантировать, что модуль не будет re-introduced как fail-OPEN facade;
    DSL/extensions продолжают использовать канонический ``RateLimiter``
    Protocol через ``infrastructure.resilience.unified_rate_limiter``.
"""

from __future__ import annotations

import importlib


def test_unified_rate_limiter_module_removed() -> None:
    """Модуль ``core.resilience.unified_rate_limiter`` не существует."""
    with __import__("pytest").raises(ModuleNotFoundError):
        importlib.import_module("src.backend.core.resilience.unified_rate_limiter")


def test_unified_rate_limiter_class_not_importable() -> None:
    """``UnifiedRateLimiter`` не доступен через ``core.resilience`` namespace."""
    from src.backend.core import resilience as resilience_pkg

    assert not hasattr(resilience_pkg, "UnifiedRateLimiter"), (
        "UnifiedRateLimiter не должен быть доступен через core.resilience "
        "(fail-OPEN facade удалён D-AUDIT-9601 follow-up)."
    )
    assert not hasattr(resilience_pkg, "RateLimitResult"), (
        "RateLimitResult не должен быть доступен через core.resilience "
        "(scaffold удалён D-AUDIT-9601 follow-up)."
    )
    assert not hasattr(resilience_pkg, "get_unified_rate_limiter"), (
        "get_unified_rate_limiter не должен быть доступен через core.resilience "
        "(scaffold удалён D-AUDIT-9601 follow-up)."
    )


def test_canonical_rate_limiter_protocol_still_works() -> None:
    """Канонический ``RateLimiter`` Protocol остался работать после удаления facade."""
    from src.backend.core.resilience.rate_limiter import (
        RateLimit,
        RateLimitExceeded,
        RateLimiter,
        RedisRateLimiter,
        get_rate_limiter,
    )

    # Singleton check
    assert get_rate_limiter() is get_rate_limiter()

    # Protocol conformance
    instance = get_rate_limiter()
    assert isinstance(instance, (RedisRateLimiter, RateLimiter))

    # Dataclass construction
    policy = RateLimit(limit=100, window_seconds=60)
    assert policy.limit == 100
    assert policy.window_seconds == 60

    # Exception carries retry_after
    exc = RateLimitExceeded(limit=10, window=60, retry_after=42)
    assert exc.retry_after == 42
    assert "42s" in str(exc)


def test_resilience_init_does_not_reexport_unified_rate_limiter() -> None:
    """``core.resilience.__init__`` не ре-экспортирует удалённый facade."""
    from src.backend.core.resilience import (
        RateLimit,
        RateLimitExceeded,
        RateLimiter,
        RedisRateLimiter,
    )

    # Canonical re-exports through __init__ still work
    assert RateLimit is not None
    assert RateLimitExceeded is not None
    assert RateLimiter is not None
    assert RedisRateLimiter is not None

    # Removed facade should NOT be in __all__ or top-level import
    import src.backend.core.resilience as resilience_mod

    assert "UnifiedRateLimiter" not in getattr(resilience_mod, "__all__", ())
    assert "RateLimitResult" not in getattr(resilience_mod, "__all__", ())
    assert "get_unified_rate_limiter" not in getattr(resilience_mod, "__all__", ())
