"""S98 W1 — regression: middleware registry full implementation status.

Pre-S98: ``core/middleware/__init__.py:12`` содержал outdated TODO
``(S18: full implementation per ADR-A-01)``. Реально ``build_chain``
уже реализован в S70 W1 — TODO был stale.

Тесты:

1. ``MiddlewareRegistry.build_chain`` — реально работает (S70 W1).
2. ``RouteMiddlewareConfig`` immutable (frozen).
3. ``register`` rejects duplicates.
4. ``has`` / ``list_registered`` API consistency.
5. ``_resolve_chain_order`` diff algorithm.
6. No TODO markers в ``core/middleware/__init__.py``.
"""

from __future__ import annotations

import pytest


def test_middleware_registry_build_chain_works() -> None:
    """``build_chain`` actual implementation (S70 W1), not scaffold."""
    from src.backend.core.middleware import MiddlewareRegistry, RouteMiddlewareConfig

    registry = MiddlewareRegistry()
    call_log: list[str] = []

    def make_mw(name: str):
        def factory(app, **kwargs):
            call_log.append(f"{name}:{kwargs.get('limit', 'default')}")
            return f"wrapped_by_{name}"

        return factory

    registry.register("rate_limit", make_mw("rate_limit"))
    registry.register("audit", make_mw("audit"))

    config = RouteMiddlewareConfig(
        include=["rate_limit", "audit"], overrides={"rate_limit": {"limit": 1000}}
    )
    result = registry.build_chain("app", config)
    # S70 W1: reduce-based wrap, outer → inner
    assert result is not None
    # Both middlewares were called
    assert "rate_limit:1000" in call_log
    assert "audit:default" in call_log


def test_route_middleware_config_immutable() -> None:
    """``RouteMiddlewareConfig`` frozen — no runtime mutation."""
    from src.backend.core.middleware import RouteMiddlewareConfig

    config = RouteMiddlewareConfig(include=["a"], exclude=["b"])
    with pytest.raises((AttributeError, TypeError)):
        config.include = ["c"]  # type: ignore[misc]


def test_register_rejects_duplicates() -> None:
    """Double ``register`` → ``ValueError``."""
    from src.backend.core.middleware import MiddlewareRegistry

    registry = MiddlewareRegistry()
    registry.register("dup", lambda app, **kw: app)
    with pytest.raises(ValueError, match="уже зарегистрирован"):
        registry.register("dup", lambda app, **kw: app)


def test_has_and_list_registered() -> None:
    """``has`` / ``list_registered`` API consistency."""
    from src.backend.core.middleware import MiddlewareRegistry

    registry = MiddlewareRegistry()
    assert registry.has("missing") is False
    assert registry.list_registered() == []

    registry.register("a", lambda app, **kw: app)
    registry.register("b", lambda app, **kw: app)

    assert registry.has("a") is True
    assert registry.has("b") is True
    # list_registered returns sorted
    assert registry.list_registered() == ["a", "b"]


def test_resolve_chain_order_diff() -> None:
    """``_resolve_chain_order`` diff algorithm (include ∩ registered − exclude)."""
    from src.backend.core.middleware import MiddlewareRegistry, RouteMiddlewareConfig

    registry = MiddlewareRegistry()
    registry.register("auth", lambda app, **kw: app)
    registry.register("audit", lambda app, **kw: app)
    registry.register("rate_limit", lambda app, **kw: app)

    # Empty include → all registered
    order = registry._resolve_chain_order(RouteMiddlewareConfig())
    assert order == ["audit", "auth", "rate_limit"]  # sorted

    # include — selected subset
    order = registry._resolve_chain_order(
        RouteMiddlewareConfig(include=["auth", "rate_limit"])
    )
    assert order == ["auth", "rate_limit"]

    # exclude — remove from selected
    order = registry._resolve_chain_order(
        RouteMiddlewareConfig(include=["auth", "rate_limit"], exclude=["auth"])
    )
    assert order == ["rate_limit"]

    # include unknown → ValueError
    with pytest.raises(ValueError, match="не зарегистрированы"):
        registry._resolve_chain_order(RouteMiddlewareConfig(include=["nonexistent"]))


def test_no_todo_in_middleware_init() -> None:
    """``core/middleware/__init__.py`` НЕ содержит ACTIVE TODO markers.

    Разрешает: исторические ссылки (``Удалён outdated TODO S18``) — это
    documentation, не actionable.
    Запрещает: actionable TODO типа ``TODO: implement X``.
    """
    from pathlib import Path

    init_file = Path("src/backend/core/middleware/__init__.py")
    src = init_file.read_text()
    # Strip history/deletion lines (per-line filter)
    actionable_lines = [
        line
        for line in src.splitlines()
        if "TODO" in line
        and "Удалён" not in line
        and "устаревший" not in line.lower()
        and "outdated" not in line.lower()
        and "history" not in line.lower()
    ]
    assert not actionable_lines, (
        f"Actionable TODO found in {init_file}:\n  " + "\n  ".join(actionable_lines)
    )
    # Нет "scaffold-only" (этот label был до S70 W1, сейчас не актуален)
    assert "scaffold-only" not in src.lower(), (
        f"'scaffold-only' word found in {init_file} — outdated label."
    )
