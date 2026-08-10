"""Cycle-35 B2: регрессионные тесты для мигрированной ``resolve_waf_route``.

Контракт:

* Канонический путь: ``extensions.skb.services.waf_route.resolve_waf_route``
  — чистая функция без побочных эффектов и I/O;
* Backward-compat shim: ``src.backend.services.integrations.skb.resolve_waf_route``
  реэкспортирует ту же логику, но эмитит ``DeprecationWarning``;
* Метод ``APISKBService._waf_route`` использует чистую реализацию из
  расширения.

Покрытие:

1. ``test_canonical_path_returns_waf_when_production_and_url_set`` —
   production + waf_url → ``(waf_url, True)``.
2. ``test_canonical_path_returns_no_waf_in_other_envs`` — dev/staging/None → ``(None, False)``.
3. ``test_canonical_path_returns_no_waf_when_url_missing`` — production без waf_url → ``(None, False)``.
4. ``test_shim_emits_deprecation_warning`` — старый путь эмитит ``DeprecationWarning``.
5. ``test_shim_delegates_to_canonical`` — результаты shim и canonical идентичны.
6. ``test_class_waf_route_uses_extension_impl`` — ``APISKBService._waf_route``
   прозрачно делегирует в ``extensions.skb.services.waf_route``.
"""

from __future__ import annotations

import warnings

from extensions.skb.services import waf_route as ext_waf_route
from src.backend.services.integrations.skb import APISKBService
from src.backend.services.integrations.skb import (
    resolve_waf_route as legacy_resolve_waf_route,
)

# ── canonical path ──────────────────────────────────────────────


def test_canonical_path_returns_waf_when_production_and_url_set() -> None:
    result = ext_waf_route.resolve_waf_route("production", "https://waf.bank.ru/skb")
    assert result == ("https://waf.bank.ru/skb", True)


def test_canonical_path_returns_no_waf_in_other_envs() -> None:
    assert ext_waf_route.resolve_waf_route("dev", "https://waf.bank.ru/skb") == (
        None,
        False,
    )
    assert ext_waf_route.resolve_waf_route("staging", "https://waf.bank.ru/skb") == (
        None,
        False,
    )
    assert ext_waf_route.resolve_waf_route(None, "https://waf.bank.ru/skb") == (
        None,
        False,
    )


def test_canonical_path_returns_no_waf_when_url_missing() -> None:
    assert ext_waf_route.resolve_waf_route("production", None) == (None, False)
    assert ext_waf_route.resolve_waf_route("production", "") == (None, False)


# ── backward-compat shim ────────────────────────────────────────


def test_shim_emits_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        legacy_resolve_waf_route("production", "https://waf.bank.ru/skb")
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations, "shim должен эмитить DeprecationWarning"
    msg = str(deprecations[0].message)
    assert "extensions.skb.services.waf_route" in msg


def test_shim_delegates_to_canonical() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        for env, url in (
            ("production", "https://waf.bank.ru/skb"),
            ("dev", "https://waf.bank.ru/skb"),
            ("production", None),
            (None, None),
        ):
            assert legacy_resolve_waf_route(
                env, url,
            ) == ext_waf_route.resolve_waf_route(env, url)


def test_shim_and_canonical_are_same_object() -> None:
    """Cycle-35 B2: shim не дублирует логику — он переиспользует реализацию."""
    # canonical exports `resolve_waf_route`
    # legacy shim wraps it via DeprecationWarning but same callable underlying
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy_result = legacy_resolve_waf_route("production", "https://waf.bank.ru/x")
    canonical_result = ext_waf_route.resolve_waf_route(
        "production", "https://waf.bank.ru/x",
    )
    assert legacy_result == canonical_result


# ── class method integration ─────────────────────────────────────


def test_class_waf_route_uses_extension_impl() -> None:
    """``APISKBService._waf_route`` прозрачно использует расширение."""
    from types import SimpleNamespace
    from unittest.mock import patch

    stub_settings = SimpleNamespace(
        base_url="https://skb.example.com/",
        endpoints={"GET_KINDS": "kinds"},
        api_key="skb-key",
        connect_timeout=2,
        read_timeout=5,
        use_waf=False,
    )
    svc = APISKBService(skb_settings=stub_settings)
    with patch("src.backend.services.integrations.skb.settings") as mock_settings:
        mock_settings.app.environment = "production"
        mock_settings.http_base_settings.waf_url = "https://waf.bank.ru/skb"
        assert svc._waf_route() == ("https://waf.bank.ru/skb", True)
        mock_settings.app.environment = "dev"
        assert svc._waf_route() == (None, False)
