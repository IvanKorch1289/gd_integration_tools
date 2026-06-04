"""Unit-тесты ``CallFunctionProcessor`` (K-ARCH-5, Sprint 17).

Покрытие:
    * strict-режим через ENV ``ENVIRONMENT=production`` — пустой
      whitelist поднимает PermissionError;
    * strict-режим через ``feature_flags.call_function_whitelist_strict``;
    * default (dev) режим — пустой whitelist разрешён;
    * happy path с whitelist (module match / wildcard);
    * deny path (module не в whitelist).
"""

# ruff: noqa: S101

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.processors.function_call import CallFunctionProcessor


def _ctx(**props: Any) -> SimpleNamespace:
    """Создать минимальный mock ExecutionContext с properties."""
    return SimpleNamespace(properties=dict(props))


class TestStrictWhitelistEmpty:
    """K-ARCH-5: пустой whitelist в strict-режиме поднимает PermissionError."""

    def test_production_env_raises_on_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(PermissionError, match="empty whitelist"):
            CallFunctionProcessor._validate_module_whitelist("anything.fn", _ctx())

    def test_feature_flag_strict_raises_on_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setattr(feature_flags, "call_function_whitelist_strict", True)
        with pytest.raises(PermissionError, match="empty whitelist"):
            CallFunctionProcessor._validate_module_whitelist("anything.fn", _ctx())

    def test_default_dev_mode_passes_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setattr(feature_flags, "call_function_whitelist_strict", False)
        # noop — без exception
        CallFunctionProcessor._validate_module_whitelist("anything.fn", _ctx())


class TestWhitelistMatching:
    """Whitelist override без strict-mode."""

    def test_module_match(self) -> None:
        ctx = _ctx(call_function_modules=["extensions.x.functions"])
        CallFunctionProcessor._validate_module_whitelist(
            "extensions.x.functions", ctx
        )  # noop

    def test_wildcard_match(self) -> None:
        ctx = _ctx(call_function_modules=["extensions.x.*"])
        CallFunctionProcessor._validate_module_whitelist(
            "extensions.x.functions", ctx
        )  # noop

    def test_no_match_raises(self) -> None:
        ctx = _ctx(call_function_modules=["extensions.allowed"])
        with pytest.raises(PermissionError, match="not in whitelist"):
            CallFunctionProcessor._validate_module_whitelist(
                "extensions.forbidden", ctx
            )


class TestStrictBypassedByWhitelist:
    """strict-режим НЕ блокирует, если whitelist непустой и module матчится."""

    def test_production_with_whitelist_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        ctx = _ctx(call_function_modules=["extensions.x.functions"])
        CallFunctionProcessor._validate_module_whitelist("extensions.x.functions", ctx)

    def test_production_with_whitelist_denies_other(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        ctx = _ctx(call_function_modules=["extensions.x.functions"])
        with pytest.raises(PermissionError, match="not in whitelist"):
            CallFunctionProcessor._validate_module_whitelist(
                "extensions.forbidden", ctx
            )


class TestCapabilityCheck:
    """K-ARCH-5: CapabilityGate.check вызывается с function.call.<module>."""

    def test_no_gate_is_noop(self) -> None:
        ctx = _ctx()
        # Без gate — no-op
        CallFunctionProcessor._check_capability("any.module", ctx)

    def test_gate_check_called(self) -> None:
        calls: list[tuple[str, str, str | None]] = []

        class _FakeGate:
            def check(self, plugin: str, capability: str, scope: str | None) -> None:
                calls.append((plugin, capability, scope))

        ctx = _ctx(capability_gate=_FakeGate(), plugin="example_plugin")
        CallFunctionProcessor._check_capability("extensions.x.fns", ctx)
        assert calls == [("example_plugin", "function.call.extensions.x.fns", None)]
