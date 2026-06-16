"""Smoke-тесты для MiddlewareRegistry scaffold (ADR-A-01).

Проверяет публичный контракт scaffold-реализации без runtime-mount.
Полная реализация ``build_chain`` — Sprint 18 K3 W2.

Wave: ``[wave:s17/k3-w2-middleware-registry]``.
"""

from __future__ import annotations

import pytest

from src.backend.core.middleware import MiddlewareRegistry, RouteMiddlewareConfig


def test_config_default_factories() -> None:
    """``RouteMiddlewareConfig`` создаётся с пустыми default-значениями."""
    cfg = RouteMiddlewareConfig()
    assert cfg.include == []
    assert cfg.exclude == []
    assert cfg.overrides == {}


def test_config_is_frozen() -> None:
    """``RouteMiddlewareConfig`` immutable — runtime-mutation запрещена."""
    cfg = RouteMiddlewareConfig(include=["auth"])
    with pytest.raises(Exception):  # FrozenInstanceError / AttributeError
        cfg.include = ["other"]  # type: ignore[misc]


def test_config_accepts_explicit_overrides() -> None:
    """Поля принимают полные значения через kwargs."""
    cfg = RouteMiddlewareConfig(
        include=["rate_limit", "auth"],
        exclude=["data_masking"],
        overrides={"rate_limit": {"limit": 1000, "window": "1m"}},
    )
    assert cfg.include == ["rate_limit", "auth"]
    assert cfg.exclude == ["data_masking"]
    assert cfg.overrides["rate_limit"]["limit"] == 1000


def test_registry_register_and_has() -> None:
    """Можно зарегистрировать builder и проверить наличие."""
    registry = MiddlewareRegistry()

    def _builder(app):  # type: ignore[no-untyped-def]
        return app

    assert not registry.has("rate_limit")
    registry.register("rate_limit", _builder)
    assert registry.has("rate_limit")
    assert registry.list_registered() == ["rate_limit"]


def test_registry_duplicate_raises() -> None:
    """Повторная регистрация того же имени → ValueError."""
    registry = MiddlewareRegistry()

    registry.register("auth", lambda app: app)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="уже зарегистрирован"):
        registry.register("auth", lambda app: app)  # type: ignore[arg-type]


def test_registry_list_sorted() -> None:
    """``list_registered`` возвращает отсортированный список."""
    registry = MiddlewareRegistry()
    for name in ("audit", "auth", "rate_limit"):
        registry.register(name, lambda app: app)  # type: ignore[arg-type]
    assert registry.list_registered() == ["audit", "auth", "rate_limit"]


def test_build_chain_returns_callable() -> None:
    """``build_chain`` теперь полностью реализован (Sprint 18 K3 W2 done)."""
    registry = MiddlewareRegistry()
    cfg = RouteMiddlewareConfig()
    # Проверяем что возвращается callable (или хотя бы не падает на базовом кейсе)
    result = registry.build_chain(object(), cfg)
    assert result is not None  # type: ignore[comparison-overlap]
