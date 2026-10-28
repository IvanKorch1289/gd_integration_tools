"""Cycle 170 tests: ``policy.cache()`` DeprecationWarning + ``cache_policy()`` migration.

ADR-0355: ``policy.cache()`` это marker (no-op), MRO-коллидит с
реальным ``RouteBuilder.cache()``. Переименовано в ``cache_policy()``
с deprecated shim.
"""

from __future__ import annotations

import warnings

import pytest

from src.backend.dsl.builders.base import RouteBuilder


class TestPolicyCacheMarker:
    def test_cache_policy_method_exists(self) -> None:
        """``PolicyMixin.cache_policy()`` — canonical (новый) метод."""
        builder = RouteBuilder.from_("test", source="http:GET /test")
        result = builder.policy.cache_policy(ttl_seconds=60)
        assert result is builder  # chainable

    def test_cache_policy_no_warning(self) -> None:
        """``cache_policy()`` не выдаёт DeprecationWarning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            RouteBuilder.from_("test", source="http:GET /test").policy.cache_policy(
                ttl_seconds=60
            )
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecations) == 0, (
            f"cache_policy() emitted DeprecationWarning: {deprecations[0].message}"
        )

    def test_cache_policy_emits_runtime_warning(self) -> None:
        """``cache_policy()`` честно предупреждает, что это marker без кэша.

        Вызов выглядит рабочим, но реального кэша нет — значит должен
        быть явный ``RuntimeWarning`` с указанием канонического пути
        для настоящего кэша (``RouteBuilder.cache(key_fn=..., ttl=...)``).
        """
        with pytest.warns(RuntimeWarning) as caught:
            RouteBuilder.from_("test", source="http:GET /test").policy.cache_policy(
                ttl_seconds=60
            )
        messages = [str(w.message) for w in caught]
        assert any("marker" in m.lower() for m in messages), (
            f"warning does not mention marker semantics: {messages}"
        )
        assert any("RouteBuilder.cache" in m for m in messages), (
            f"warning does not name the real cache path: {messages}"
        )
        assert any("key_fn" in m for m in messages), (
            f"warning does not mention the real cache signature: {messages}"
        )

    def test_cache_emits_deprecation_warning(self) -> None:
        """``cache()`` выдаёт DeprecationWarning (ADR-0355)."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            RouteBuilder.from_("test", source="http:GET /test").policy.cache(
                ttl_seconds=60
            )
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecations) >= 1
        assert "ADR-0355" in str(deprecations[0].message)
        assert "cache_policy" in str(deprecations[0].message)

    def test_cache_still_chainable(self) -> None:
        """``cache()`` (deprecated) всё ещё chainable через shim."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = (
                RouteBuilder.from_("test", source="http:GET /test")
                .policy.cache(ttl_seconds=60)
                .policy.cache_policy(ttl_seconds=120)
            )
        assert result is not None
        # Check both methods добавлены processors.
        assert len(result._processors) >= 2  # type: ignore[attr-defined]
