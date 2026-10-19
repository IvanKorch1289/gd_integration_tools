"""Tests for ``src.backend.infrastructure.messaging.dlq.policy_resolver``.

S13 K3 W4: DLQ class resolver для envelope на основании route manifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from src.backend.infrastructure.messaging.dlq import policy_resolver as mod
from src.backend.infrastructure.messaging.dlq.policy_resolver import (
    resolve_class_for_envelope,
    resolve_policy_for,
)


@dataclass
class _FakeEnvelope:
    """Минимальная заглушка DLQEnvelope."""

    dlq_class: str = "operational"


@dataclass
class _FakeDLQConfig:
    dlq_class: str = ""


@dataclass
class _FakeManifest:
    dlq: _FakeDLQConfig = field(default_factory=_FakeDLQConfig)


class TestResolveClassNoArgs:
    """Defaults: возвращает envelope.dlq_class или 'operational'."""

    def test_returns_envelope_default(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        assert resolve_class_for_envelope(env) == "operational"

    def test_empty_envelope_returns_operational(self) -> None:
        env = _FakeEnvelope(dlq_class="")
        assert resolve_class_for_envelope(env) == "operational"

    def test_envelope_with_custom_class(self) -> None:
        env = _FakeEnvelope(dlq_class="financial")
        assert resolve_class_for_envelope(env) == "financial"


class TestResolveClassRouteManifest:
    """route_manifest имеет наивысший приоритет."""

    def test_manifest_explicit_override(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        manifest = _FakeManifest(dlq=_FakeDLQConfig(dlq_class="critical"))
        assert (
            resolve_class_for_envelope(env, route_manifest=manifest) == "critical"
        )

    def test_manifest_overrides_dispatch_category(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        manifest = _FakeManifest(dlq=_FakeDLQConfig(dlq_class="custom"))
        result = resolve_class_for_envelope(
            env, route_manifest=manifest, dispatch_action_category="financial"
        )
        assert result == "custom"

    def test_manifest_with_empty_dlq_class_falls_through(self) -> None:
        # Если dlq.dlq_class пустой — fallback на следующий уровень
        env = _FakeEnvelope(dlq_class="operational")
        manifest = _FakeManifest(dlq=_FakeDLQConfig(dlq_class=""))
        result = resolve_class_for_envelope(env, route_manifest=manifest)
        assert result == "operational"

    def test_manifest_without_dlq_attribute(self) -> None:
        # Manifest без атрибута dlq — fallback
        env = _FakeEnvelope(dlq_class="operational")
        # Простой объект без dlq
        result = resolve_class_for_envelope(env, route_manifest=object())
        assert result == "operational"

    def test_manifest_with_none_dlq(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        manifest = MagicMock()
        manifest.dlq = None
        result = resolve_class_for_envelope(env, route_manifest=manifest)
        assert result == "operational"


class TestResolveClassDispatchCategory:
    """dispatch_action_category — второй приоритет."""

    def test_financial_category(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        result = resolve_class_for_envelope(
            env, dispatch_action_category="financial"
        )
        assert result == "financial"

    def test_analytics_category(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        result = resolve_class_for_envelope(
            env, dispatch_action_category="analytics"
        )
        assert result == "analytics"

    def test_operational_category(self) -> None:
        env = _FakeEnvelope(dlq_class="financial")
        result = resolve_class_for_envelope(
            env, dispatch_action_category="operational"
        )
        assert result == "operational"

    def test_unknown_category_falls_back_to_envelope(self) -> None:
        env = _FakeEnvelope(dlq_class="financial")
        result = resolve_class_for_envelope(
            env, dispatch_action_category="unknown_xyz"
        )
        # mapping.get('unknown_xyz') → None → falls through
        assert result == "financial"

    def test_category_lowercased(self) -> None:
        # "FINANCIAL" → "financial" (lowercase перед mapping.get)
        env = _FakeEnvelope(dlq_class="operational")
        result = resolve_class_for_envelope(
            env, dispatch_action_category="FINANCIAL"
        )
        assert result == "financial"


class TestResolveClassPriority:
    """Приоритет: manifest > category > envelope."""

    def test_all_three_provided_manifest_wins(self) -> None:
        env = _FakeEnvelope(dlq_class="envelope_value")
        manifest = _FakeManifest(dlq=_FakeDLQConfig(dlq_class="manifest_value"))
        result = resolve_class_for_envelope(
            env,
            route_manifest=manifest,
            dispatch_action_category="financial",
        )
        assert result == "manifest_value"

    def test_no_manifest_category_overrides_envelope(self) -> None:
        env = _FakeEnvelope(dlq_class="envelope_value")
        result = resolve_class_for_envelope(
            env, dispatch_action_category="financial"
        )
        assert result == "financial"

    def test_no_manifest_no_category_uses_envelope(self) -> None:
        env = _FakeEnvelope(dlq_class="envelope_value")
        result = resolve_class_for_envelope(env)
        assert result == "envelope_value"

    def test_none_manifest_uses_category(self) -> None:
        env = _FakeEnvelope(dlq_class="envelope_value")
        result = resolve_class_for_envelope(
            env,
            route_manifest=None,
            dispatch_action_category="financial",
        )
        assert result == "financial"

    def test_none_category_uses_envelope(self) -> None:
        env = _FakeEnvelope(dlq_class="envelope_value")
        result = resolve_class_for_envelope(
            env, dispatch_action_category=None
        )
        assert result == "envelope_value"


class TestResolveClassEmptyStringManifest:
    """Edge case: manifest.dlq.dlq_class = '' — falsy, fall through."""

    def test_empty_string_manifest_falls_through_to_category(self) -> None:
        env = _FakeEnvelope(dlq_class="envelope_value")
        manifest = _FakeManifest(dlq=_FakeDLQConfig(dlq_class=""))
        result = resolve_class_for_envelope(
            env,
            route_manifest=manifest,
            dispatch_action_category="financial",
        )
        # Empty falsy → falls through to category
        assert result == "financial"

    def test_empty_string_manifest_falls_through_to_envelope(self) -> None:
        env = _FakeEnvelope(dlq_class="envelope_value")
        manifest = _FakeManifest(dlq=_FakeDLQConfig(dlq_class=""))
        result = resolve_class_for_envelope(env, route_manifest=manifest)
        assert result == "envelope_value"


class TestResolvePolicyFor:
    """resolve_policy_for() — обёртка над registry.get_or_default."""

    def test_uses_class_name_from_resolver(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        # Mock registry
        registry = MagicMock()
        sentinel_policy = object()
        registry.get_or_default.return_value = sentinel_policy

        result = resolve_policy_for(env, registry=registry)
        assert result is sentinel_policy
        # registry.get_or_default должен быть вызван с 'operational'
        registry.get_or_default.assert_called_once_with("operational")

    def test_manifest_propagates_to_class_resolver(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        registry = MagicMock()
        sentinel = object()
        registry.get_or_default.return_value = sentinel
        manifest = _FakeManifest(dlq=_FakeDLQConfig(dlq_class="critical"))

        result = resolve_policy_for(
            env, registry=registry, route_manifest=manifest
        )
        assert result is sentinel
        registry.get_or_default.assert_called_once_with("critical")

    def test_category_propagates_to_class_resolver(self) -> None:
        env = _FakeEnvelope(dlq_class="operational")
        registry = MagicMock()
        sentinel = object()
        registry.get_or_default.return_value = sentinel

        result = resolve_policy_for(
            env, registry=registry, dispatch_action_category="financial"
        )
        assert result is sentinel
        registry.get_or_default.assert_called_once_with("financial")


class TestAllExports:
    """__all__ проверка."""

    def test_exports_two_functions(self) -> None:
        assert "resolve_class_for_envelope" in mod.__all__
        assert "resolve_policy_for" in mod.__all__
        assert len(mod.__all__) == 2

    def test_functions_callable(self) -> None:
        assert callable(resolve_class_for_envelope)
        assert callable(resolve_policy_for)


class TestTypeHints:
    """Type hints корректные."""

    def test_resolve_class_accepts_route_manifest_kwarg(self) -> None:
        import inspect

        sig = inspect.signature(resolve_class_for_envelope)
        params = sig.parameters
        assert "route_manifest" in params
        assert "dispatch_action_category" in params

    def test_resolve_policy_accepts_registry_kwarg(self) -> None:
        import inspect

        sig = inspect.signature(resolve_policy_for)
        params = sig.parameters
        assert "registry" in params
        assert "route_manifest" in params
        assert "dispatch_action_category" in params