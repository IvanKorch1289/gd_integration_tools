"""Regression: ``core/di/providers/ai.py`` ``get_skill_registry`` had
``except Exception as exc:`` with ``exc`` unused (F841). The fix drops
the name. This test ensures the provider still returns ``None`` when
``app_state_singleton`` raises — that was the only side effect."""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.di.providers import ai as ai_providers


class TestSkillRegistryProvider:
    def test_returns_none_on_singleton_failure(self) -> None:
        # The function does ``from src.backend.core.di import app_state_singleton``
        # at call time, so we patch the symbol in the source module.
        di_module = sys.modules["src.backend.core.di"]

        def _boom(*_a: object, **_kw: object) -> None:
            raise RuntimeError("no app state")

        with patch.object(di_module, "app_state_singleton", _boom):
            assert ai_providers.get_skill_registry() is None

    def test_returns_singleton_when_available(self) -> None:
        sentinel = object()

        def _factory() -> object:
            return sentinel

        di_module = sys.modules["src.backend.core.di"]

        def _stub_app_state(*_a: object, **_kw: object) -> Any:
            return _factory

        with patch.object(di_module, "app_state_singleton", _stub_app_state):
            assert ai_providers.get_skill_registry() is sentinel
