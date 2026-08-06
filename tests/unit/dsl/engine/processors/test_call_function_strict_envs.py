"""D-AUDIT-#20 strict-env test для CallFunctionProcessor._is_strict_whitelist.

Per multi-agent audit (Sprint 182 verify): pre-fix code only treated
``ENVIRONMENT=production`` as strict. ``staging`` / ``dev_staging`` получали
dev-bypass (empty whitelist = allow). S183 W2 #2 fix закрывает gap: эти
envs тоже strict-mode.

Strict test policy per D-LESSON-11: NO lax placeholders.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.dsl.engine.processors.function_call import CallFunctionProcessor

_STRICT_ENVS = ("production", "prod", "staging", "dev_staging")
_PERMISSIVE_ENVS = ("dev", "dev_light", "test", "ci", "")


@pytest.mark.parametrize("env", _STRICT_ENVS)
def test_strict_envs_return_true(monkeypatch, env: str) -> None:
    """Production/staging/dev_staging trigger strict-mode automatically (env-only)."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ENVIRONMENT", env)
    # Force feature flag path to permissive so we verify env-only path:
    with patch(
        "src.backend.core.config.features.feature_flags.call_function_whitelist_strict",
        False,
    ):
        assert CallFunctionProcessor._is_strict_whitelist() is True, (
            f"ENV={env!r} must trigger strict whitelist per D-AUDIT-#20"
        )


@pytest.mark.parametrize("env", _PERMISSIVE_ENVS)
def test_permissive_envs_fall_through(monkeypatch, env: str) -> None:
    """Dev_light / test / empty env must NOT trigger strict (dev-bypass preserved)."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    if env:
        monkeypatch.setenv("ENVIRONMENT", env)
    with patch(
        "src.backend.core.config.features.feature_flags.call_function_whitelist_strict",
        False,
    ):
        assert CallFunctionProcessor._is_strict_whitelist() is False, (
            f"ENV={env!r} must remain permissive per project convention"
        )


def test_strict_feature_flag_overrides_permissive_env(monkeypatch) -> None:
    """FF=strict + env=dev_light → strict (FF takes precedence over env)."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "dev_light")
    with patch(
        "src.backend.core.config.features.feature_flags.call_function_whitelist_strict",
        True,
    ):
        assert CallFunctionProcessor._is_strict_whitelist() is True


def test_strict_flag_disabled_on_production_env_still_strict(monkeypatch) -> None:
    """FF=permissive + env=production → strict (env takes precedence)."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with patch(
        "src.backend.core.config.features.feature_flags.call_function_whitelist_strict",
        False,
    ):
        assert CallFunctionProcessor._is_strict_whitelist() is True


def test_strict_function_call_empty_whitelist_raises(monkeypatch) -> None:
    """End-to-end: strict env + empty whitelist → PermissionError path active.

    We verify helper returns True so upstream PermissionError path activates.
    Full end-to-end test lives in dedicated tests/unit/dsl/engine/processors/
    test_call_function_whitelist_strict.py (S177-5 regression) — D-AUDIT-#20
    closes the env=staging gap so that test must now pass for staging env too.
    """
    # Strict env (staging per D-AUDIT-#20); FF flag off.
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with patch(
        "src.backend.core.config.features.feature_flags.call_function_whitelist_strict",
        False,
    ):
        assert CallFunctionProcessor._is_strict_whitelist() is True
