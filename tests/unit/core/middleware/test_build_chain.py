"""Unit-тесты MiddlewareRegistry.build_chain (S70 W1).

Проверяют:

1. Empty config → all registered middleware в chain.
2. include=[a, b] → only a, b в указанном порядке.
3. include=[a, b, c] + exclude=[b] → a, c (exclude removes).
4. include=[unknown] → raise ValueError.
5. overrides → applied как ``**kwargs`` в builder.
6. Empty include + no registered → app возвращается as-is.
7. Composition order: последний в selected = самый внешний (Starlette LIFO).

Composition semantics:
    ``reduce(wrap, [a, b, c], app)`` эквивалентно:
        step1 = wrap(app, a)        # = a wraps app
        step2 = wrap(step1, b)      # = b wraps (a wraps app)
        step3 = wrap(step2, c)      # = c wraps (b wraps (a wraps app))
    Результат: c outermost, a innermost.
    Это совпадает с Starlette ``add_middleware`` (LIFO): последний = outer.
"""

from __future__ import annotations

import pytest

from src.backend.core.middleware.registry import (
    MiddlewareRegistry,
    RouteMiddlewareConfig,
)


def _make_registry_with_3() -> MiddlewareRegistry:
    """Реестр с 3 middleware: rate_limit, audit, auth."""
    reg = MiddlewareRegistry()
    reg.register("rate_limit", lambda app, **kw: ("rate_limit", app, kw))
    reg.register("audit", lambda app, **kw: ("audit", app, kw))
    reg.register("auth", lambda app, **kw: ("auth", app, kw))
    return reg


def test_register_duplicate_raises() -> None:
    """Повторная регистрация → ValueError."""
    reg = MiddlewareRegistry()
    reg.register("a", lambda app, **kw: app)
    with pytest.raises(ValueError, match="уже зарегистрирован"):
        reg.register("a", lambda app, **kw: app)


def test_has_and_list_registered() -> None:
    """has() и list_registered() работают."""
    reg = _make_registry_with_3()
    assert reg.has("rate_limit")
    assert reg.has("audit")
    assert not reg.has("unknown")
    assert reg.list_registered() == ["audit", "auth", "rate_limit"]  # sorted


def test_build_chain_empty_config_uses_all() -> None:
    """Empty config → все зарегистрированные в sorted order.

    list_registered() возвращает sorted: [audit, auth, rate_limit].
    Reduce: outermost = rate_limit (last in sorted), innermost = audit.
    """
    reg = _make_registry_with_3()
    config = RouteMiddlewareConfig()  # include=[]

    result = reg.build_chain("app", config)

    # outermost wrapper = rate_limit
    assert result[0] == "rate_limit"
    # next = auth
    assert result[1][0] == "auth"
    # innermost = audit (wraps original app)
    assert result[1][1][0] == "audit"
    assert result[1][1][1] == "app"


def test_build_chain_include_subset() -> None:
    """include=[rate_limit, auth] → only those, в указанном порядке.

    Reduce: outermost = auth (last in selected), innermost = rate_limit.
    """
    reg = _make_registry_with_3()
    config = RouteMiddlewareConfig(include=["rate_limit", "auth"])

    result = reg.build_chain("app", config)

    # outermost = auth
    assert result[0] == "auth"
    # innermost = rate_limit (wraps app)
    assert result[1][0] == "rate_limit"
    assert result[1][1] == "app"


def test_build_chain_exclude() -> None:
    """include=[rate_limit, audit, auth] + exclude=[audit] → rate_limit + auth.

    Reduce: selected = [rate_limit, auth], outermost = auth, innermost = rate_limit.
    """
    reg = _make_registry_with_3()
    config = RouteMiddlewareConfig(
        include=["rate_limit", "audit", "auth"],
        exclude=["audit"],
    )

    result = reg.build_chain("app", config)

    assert result[0] == "auth"
    assert result[1][0] == "rate_limit"
    assert result[1][1] == "app"


def test_build_chain_unknown_middleware_raises() -> None:
    """include=[unknown] → ValueError."""
    reg = _make_registry_with_3()
    config = RouteMiddlewareConfig(include=["rate_limit", "ghost"])

    with pytest.raises(ValueError, match="не зарегистрированы"):
        reg.build_chain("app", config)


def test_build_chain_overrides_applied_as_kwargs() -> None:
    """overrides[rate_limit] = {limit: 1000} → builder получит limit=1000."""
    reg = _make_registry_with_3()
    config = RouteMiddlewareConfig(
        include=["rate_limit"],
        overrides={"rate_limit": {"limit": 1000, "window": "1m"}},
    )

    result = reg.build_chain("app", config)

    # result = ("rate_limit", "app", {"limit": 1000, "window": "1m"})
    assert result[0] == "rate_limit"
    assert result[1] == "app"
    assert result[2] == {"limit": 1000, "window": "1m"}


def test_build_chain_no_registered_returns_app_as_is() -> None:
    """Пустой реестр + empty config → app без изменений."""
    reg = MiddlewareRegistry()
    config = RouteMiddlewareConfig()

    result = reg.build_chain("original_app", config)

    assert result == "original_app"


def test_build_chain_all_excluded_returns_app_as_is() -> None:
    """include=[a, b] + exclude=[a, b] → app as-is."""
    reg = _make_registry_with_3()
    config = RouteMiddlewareConfig(
        include=["rate_limit", "audit", "auth"],
        exclude=["rate_limit", "audit", "auth"],
    )

    result = reg.build_chain("app", config)

    assert result == "app"


def test_build_chain_last_in_selected_is_outermost() -> None:
    """Starlette LIFO: последний в selected = самый внешний."""
    reg = _make_registry_with_3()
    config = RouteMiddlewareConfig(include=["audit", "auth", "rate_limit"])

    result = reg.build_chain("app", config)

    # Outermost = rate_limit (last in include list)
    assert result[0] == "rate_limit"
    # Next = auth
    assert result[1][0] == "auth"
    # Innermost = audit (first in include list, wraps original app)
    assert result[1][1][0] == "audit"
    assert result[1][1][1] == "app"
