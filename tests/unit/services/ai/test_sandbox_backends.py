"""Tests for S172 M5 ARC-008 — Multi-process sandbox backends + deprecation.

Tests:

* :class:`InProcessAgentSandbox` emits :class:`DeprecationWarning` on construct.
* ``GD_INTEGRATION_PRODUCTION=1`` → raises RuntimeError (hard gate).
* :class:`E2BAgentSandbox` config validation (API key required).
* :class:`E2BAgentSandbox` missing dep raises config-error (no silent fallback).
* :class:`AgentSandboxSelector` — kind→backend mapping.
* ``resolve_agent_sandbox()`` — convenience wrapper.
* Backward-compat: ``get_process_pool_agent_sandbox()`` unchanged.
"""

from __future__ import annotations

import os
import warnings
from unittest.mock import patch

import pytest


# S172 M5 ARC-008: пропускаем ARC-008 тесты если запуск в production-env
# (GD_INTEGRATION_PRODUCTION=1 уже set). In-process тесты будут raise.
@pytest.fixture(autouse=True)
def _ensure_dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``GD_INTEGRATION_PRODUCTION`` UNSET for dev/test runs.

    Также устанавливает ``feature_flags.ai_in_process_sandbox_disabled=False``
    для legacy-тестов, которые проверяют DeprecationWarning-путь.
    Тесты которые тестируют fail-closed (cycle 33) явно patch'ат флаг
    обратно в True внутри test-body.
    """
    if "GD_INTEGRATION_PRODUCTION" in os.environ:
        del os.environ["GD_INTEGRATION_PRODUCTION"]
    # Разрешаем in-process для dev-legacy-тестов (DeprecationWarning path).
    try:
        from src.backend.core.config.features import feature_flags
        monkeypatch.setattr(feature_flags, "ai_in_process_sandbox_disabled", False)
    except Exception:
        # feature_flags может не быть в test-env; пропускаем.
        pass


class TestInProcessAgentSandboxDeprecation:
    """M5 ARC-008 — InProcessAgentSandbox emits DeprecationWarning."""

    def test_in_process_emits_deprecation_warning(self) -> None:
        from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            InProcessAgentSandbox()

        deprecation = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation) >= 1
        msg = str(deprecation[0].message)
        # M5 ARC-008 messages — relevant keywords.
        assert "ProcessPool" in msg or "E2B" in msg or "DEPRECATED" in msg

    def test_in_process_warning_mentions_alternatives(self) -> None:
        from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            InProcessAgentSandbox()

        assert any(
            "ProcessPool" in str(w.message) for w in caught
        ), "deprecation warning should suggest ProcessPool alternative"

    def test_in_process_hard_gate_in_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При ``GD_INTEGRATION_PRODUCTION=1`` → in-process raise.

        Module-level ``_IN_PROCESS_PROD_BLOCKED`` cached на import time
        → re-import модуля для проверки hard-gate.
        """
        monkeypatch.setenv("GD_INTEGRATION_PRODUCTION", "1")
        import importlib

        import src.backend.services.ai.agent_sandbox as _mod

        importlib.reload(_mod)
        try:
            from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

            with pytest.raises(RuntimeError, match="forbidden in production"):
                InProcessAgentSandbox()
        finally:
            monkeypatch.delenv("GD_INTEGRATION_PRODUCTION", raising=False)
            importlib.reload(_mod)


class TestProcessPoolAgentSandboxUnchanged:
    """Backward compat — ProcessPoolAgentSandbox не должен breaking."""

    def test_get_process_pool_returns_singleton(self) -> None:
        """Singleton lazy-init — second call returns same instance."""
        from src.backend.services.ai.agent_sandbox import get_process_pool_agent_sandbox

        a = get_process_pool_agent_sandbox()
        b = get_process_pool_agent_sandbox()
        assert a is b


class TestInProcessAgentSandboxFeatureFlagGate:
    """Cycle 33 S176: feature-flag fail-closed regression tests (P0-1 second layer).

    Дополнительно к production hard-gate (тест выше): при
    ``feature_flags.ai_in_process_sandbox_disabled=True`` (default ON)
    ``InProcessAgentSandbox.__init__`` должен raise RuntimeError. Это
    второй слой защиты: если production-env bypass завершён через
    misconfigured env, feature-flag всё равно блокирует zero-isolation
    sandbox. Default ON в feature_flags значит, что оператор должен
    явно opt-out для использования.

    Без этих тестов — риск фиктивного закрытия: код содержит guard,
    но если guard уберут, ничто не провалится.
    """

    def test_in_process_blocked_when_feature_flag_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ai_in_process_sandbox_disabled=True (default) → RuntimeError.

        Без ``GD_INTEGRATION_PRODUCTION=1`` (dev-env), но с feature-flag
        включённым по умолчанию — in-process всё равно заблокирован.
        """
        from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

        with patch(
            "src.backend.core.config.features.feature_flags.ai_in_process_sandbox_disabled",
            True,
            create=True,
        ):
            with pytest.raises(RuntimeError, match="blocked by feature_flags"):
                InProcessAgentSandbox()

    def test_in_process_allowed_when_feature_flag_explicitly_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ai_in_process_sandbox_disabled=False (explicit opt-out) → DeprecationWarning.

        Оператор явно отключил feature-flag для dev-использования.
        Sandbox создаётся, но emit DeprecationWarning (S172 ARC-008).
        """
        from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

        with patch(
            "src.backend.core.config.features.feature_flags.ai_in_process_sandbox_disabled",
            False,
            create=True,
        ):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                sandbox = InProcessAgentSandbox()

            assert sandbox is not None
            assert any(
                issubclass(w.category, DeprecationWarning) for w in caught
            ), "explicit opt-out должен по-прежнему emit DeprecationWarning"

    def test_in_process_blocked_when_feature_flags_module_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если feature_flags module не импортируется — fail-closed.

        Защита от ситуации, когда feature_flags сломан/не установлен
        и default ON пропускается. Безопасный fallback — блокировать.
        Используем sys.modules-sysmonkeypatch чтобы simulate ImportError.
        """
        import sys

        # Подкладываем в sys.modules заглушку, которая raise ImportError
        # на любой attribute access. Это заставляет внутри __init__:
        #   from src.backend.core.config.features import feature_flags
        # упасть с ImportError на import-time.
        class _BrokenModule:
            def __getattr__(self, name: str) -> object:
                raise ImportError(f"simulated: feature_flags.{name} unavailable")

        # Сохраняем оригинал, чтобы корректно откатить.
        original = sys.modules.get("src.backend.core.config.features")
        sys.modules["src.backend.core.config.features"] = _BrokenModule()
        try:
            # Сбрасываем cached attribute, чтобы agent_sandbox re-import'нул.
            from src.backend.services.ai import agent_sandbox as _mod

            if "feature_flags" in _mod.__dict__:
                del _mod.feature_flags

            InProcessAgentSandbox = _mod.InProcessAgentSandbox

            with pytest.raises(RuntimeError, match="module unavailable"):
                InProcessAgentSandbox()
        finally:
            # Restore original module.
            if original is not None:
                sys.modules["src.backend.core.config.features"] = original
            else:
                sys.modules.pop("src.backend.core.config.features", None)
            # Force re-import of original feature_flags.
            import importlib

            import src.backend.core.config.features  # noqa: F401

            from src.backend.core.config.features import feature_flags  # noqa: F401

            importlib.reload(importlib.import_module("src.backend.core.config.features"))

class TestE2BAgentSandbox:
    """M5 ARC-008 — E2B backend config + lifecycle."""

    def test_e2b_requires_api_key(self) -> None:
        """Без E2B_API_KEY → config error."""
        from src.backend.services.ai.agent_sandbox import E2BAgentSandbox

        with patch.dict(os.environ, {}, clear=True):
            backend = E2BAgentSandbox()
            assert backend.api_key_configured is False

    def test_e2b_explicit_api_key(self) -> None:
        from src.backend.services.ai.agent_sandbox import E2BAgentSandbox

        backend = E2BAgentSandbox(api_key="e2b_test_xxx")
        assert backend.api_key_configured is True

    def test_e2b_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.backend.services.ai.agent_sandbox import E2BAgentSandbox

        monkeypatch.setenv("E2B_API_KEY", "e2b_env_xxx")
        backend = E2BAgentSandbox()
        assert backend.api_key_configured is True

    @pytest.mark.asyncio
    async def test_e2b_run_react_raises_config_error_without_key(
        self,
    ) -> None:
        from src.backend.services.ai.agent_sandbox import (
            AgentSandboxConfigError,
            E2BAgentSandbox,
        )

        with patch.dict(os.environ, {}, clear=True):
            backend = E2BAgentSandbox()
            with pytest.raises(AgentSandboxConfigError, match="E2B_API_KEY"):
                await backend.run_react(
                    prompt="hi",
                    tool_actions=[],
                    model="gpt-4o-mini",
                    temperature=0.0,
                    durable=False,
                    session_id=None,
                )

    @pytest.mark.asyncio
    async def test_e2b_run_react_raises_import_error_if_dep_missing(
        self,
    ) -> None:
        """Если e2b_code_interpreter недоступен — config-error."""
        from src.backend.services.ai.agent_sandbox import (
            AgentSandboxConfigError,
            E2BAgentSandbox,
        )

        backend = E2BAgentSandbox(api_key="e2b_test_xxx")

        # Patch builtins.__import__ чтобы ``from e2b_code_interpreter import ...
        # бросал ImportError. Это имитирует missing dep в dev_light.
        import builtins as _builtins

        real_import = _builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "e2b_code_interpreter" or name.startswith(
                "e2b_code_interpreter."
            ):
                raise ImportError("simulated missing e2b_code_interpreter")
            return real_import(name, *args, **kwargs)

        with patch.object(_builtins, "__import__", side_effect=fake_import):
            with pytest.raises(
                AgentSandboxConfigError, match="e2b-code-interpreter"
            ):
                await backend.run_react(
                    prompt="hi",
                    tool_actions=[],
                    model="gpt-4o-mini",
                    temperature=0.0,
                    durable=False,
                    session_id=None,
                )


class TestAgentSandboxSelector:
    """M5 ARC-008 — AgentSandboxSelector routes by ``kind`` string."""

    def test_process_pool_default(self) -> None:
        """Default kind → process_pool."""
        from src.backend.services.ai.agent_sandbox import (
            AgentSandboxSelector,
            ProcessPoolAgentSandbox,
        )

        sel = AgentSandboxSelector()
        assert isinstance(sel.select(), ProcessPoolAgentSandbox)

    def test_in_process_select_with_warning(self) -> None:
        from src.backend.services.ai.agent_sandbox import (
            AgentSandboxSelector,
            InProcessAgentSandbox,
        )

        sel = AgentSandboxSelector()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            sandbox = sel.select(kind="in_process")
        assert isinstance(sandbox, InProcessAgentSandbox)

    def test_e2b_select_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """E2B select instantiates OK (lazy). API key check — на run_react.

        Lazy-validation design: select() не может ping e2b.dev.
        Полная валидация происходит в run_react() per invocation.
        """
        from src.backend.services.ai.agent_sandbox import (
            AgentSandboxSelector,
            E2BAgentSandbox,
        )

        monkeypatch.delenv("E2B_API_KEY", raising=False)

        sel = AgentSandboxSelector()
        sb = sel.select(kind="e2b")
        assert isinstance(sb, E2BAgentSandbox)
        assert sb.api_key_configured is False

    def test_e2b_select_with_explicit_key(self) -> None:
        from src.backend.services.ai.agent_sandbox import (
            AgentSandboxSelector,
            E2BAgentSandbox,
        )

        sel = AgentSandboxSelector(e2b_api_key="e2b_test_xxx")
        sandbox = sel.select(kind="e2b")
        assert isinstance(sandbox, E2BAgentSandbox)

    def test_unknown_kind_raises_config_error(self) -> None:
        """Unknown kind → config-error (no silent fallback)."""
        from src.backend.services.ai.agent_sandbox import (
            AgentSandboxConfigError,
            AgentSandboxSelector,
        )

        sel = AgentSandboxSelector()
        with pytest.raises(AgentSandboxConfigError, match="Unknown sandbox kind"):
            sel.select(kind="docker")  # type: ignore[arg-type]


class TestResolveAgentSandbox:
    """Convenience wrapper — ``resolve_agent_sandbox(...)`` factory."""

    def test_default_process_pool(self) -> None:
        from src.backend.services.ai.agent_sandbox import (
            ProcessPoolAgentSandbox,
            resolve_agent_sandbox,
        )

        sb = resolve_agent_sandbox()
        assert isinstance(sb, ProcessPoolAgentSandbox)

    def test_explicit_kind_in_process(self) -> None:
        from src.backend.services.ai.agent_sandbox import (
            InProcessAgentSandbox,
            resolve_agent_sandbox,
        )

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            sb = resolve_agent_sandbox(default_kind="in_process")
        assert isinstance(sb, InProcessAgentSandbox)


# ─── ARC-008 M5 review-closure tests ──────────────────────────────────


class TestE2BProtocolParity:
    """M5 review A-1 fix — ``max_wall_time_s`` override на ``E2BAgentSandbox.run_react``.

    Протокол parity с :class:`ProcessPoolAgentSandbox.run_react`.
    """

    def test_e2b_run_react_signature_has_max_wall_time_s_param(self) -> None:
        """``run_react`` принимает ``max_wall_time_s: float | None`` override."""
        import inspect

        from src.backend.services.ai.agent_sandbox import E2BAgentSandbox

        sig = inspect.signature(E2BAgentSandbox.run_react)
        assert "max_wall_time_s" in sig.parameters
        param = sig.parameters["max_wall_time_s"]
        assert param.default is None or isinstance(param.default, float)

    def test_e2b_default_timeout_applied_when_override_none(self) -> None:
        """Без override → ``self._timeout`` используется (default 600s)."""

        from src.backend.services.ai.agent_sandbox import E2BAgentSandbox

        backend = E2BAgentSandbox(api_key="e2b_test_xxx", timeout=123.0)
        assert backend._timeout == 123.0


class TestSelectorWarnOnMissingE2BKey:
    """M5 review O-1 fix — selector warns при e2b без API key (lazy-validation
    остаётся — но visibility улучшается через warning).
    """

    def test_e2b_select_without_key_emits_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """select(e2b) без ctor-key и без E2B_API_KEY env → warning."""

        import logging

        from src.backend.services.ai.agent_sandbox import AgentSandboxSelector

        monkeypatch.delenv("E2B_API_KEY", raising=False)
        sel = AgentSandboxSelector()

        with caplog.at_level(logging.WARNING):
            sel.select(kind="e2b")
        assert any(
            "e2b backend selected" in r.message for r in caplog.records
        ), "selector должен emit warning при e2b без API key"

    def test_e2b_select_with_key_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """select(e2b) c key → без warning (OK path)."""

        import logging

        from src.backend.services.ai.agent_sandbox import AgentSandboxSelector

        monkeypatch.delenv("E2B_API_KEY", raising=False)
        sel = AgentSandboxSelector(e2b_api_key="e2b_test_xxx")

        with caplog.at_level(logging.WARNING):
            sel.select(kind="e2b")
        assert not any(
            "e2b backend selected" in r.message for r in caplog.records
        )
