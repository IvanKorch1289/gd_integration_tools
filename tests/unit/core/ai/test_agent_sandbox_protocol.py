"""Tests for ``src.backend.core.ai.agent_sandbox_protocol``.

Core-level контракт AgentSandbox: Protocol + dataclass.
Реализации в services.ai.agent_sandbox (composition layer).

Тесты:
- AgentSandboxResult: frozen dataclass, defaults, equality, hashing
- AgentSandbox: runtime_checkable Protocol, duck typing
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, fields
from typing import Any

import pytest

from src.backend.core.ai.agent_sandbox_protocol import (
    AgentSandbox,
    AgentSandboxResult,
)


# ── AgentSandboxResult ───────────────────────────────────────────────


class TestAgentSandboxResultConstruction:
    """Базовое создание dataclass."""

    def test_construction_with_required_fields(self) -> None:
        """Все 3 поля обязательны (нет defaults)."""
        result = AgentSandboxResult(
            success=True,
            data={"output": "answer"},
            backend="e2b",
        )
        assert result.success is True
        assert result.data == {"output": "answer"}
        assert result.backend == "e2b"

    def test_failure_case(self) -> None:
        """``success=False`` + data с error key."""
        result = AgentSandboxResult(
            success=False,
            data={"error": "tool timeout"},
            backend="pyodide",
        )
        assert result.success is False
        assert result.data == {"error": "tool timeout"}
        assert result.backend == "pyodide"

    def test_empty_data(self) -> None:
        """Пустой data dict — допустим (без output)."""
        result = AgentSandboxResult(success=True, data={}, backend="e2b")
        assert result.data == {}


class TestAgentSandboxResultFrozen:
    """Frozen + slots — проверка immutability."""

    def test_assignment_raises(self) -> None:
        result = AgentSandboxResult(success=True, data={}, backend="e2b")
        with pytest.raises(FrozenInstanceError):
            result.success = False  # type: ignore[misc]

    def test_backend_assignment_raises(self) -> None:
        result = AgentSandboxResult(success=True, data={}, backend="e2b")
        with pytest.raises(FrozenInstanceError):
            result.backend = "pyodide"  # type: ignore[misc]

    def test_data_inplace_works(self) -> None:
        """Frozen защищает top-level assignment, не in-place мутацию dict.

        Это by design (см. test_auth_result.py для аналогичной семантики).
        """
        result = AgentSandboxResult(success=True, data={"k": "v"}, backend="e2b")
        # Не бросает (mutable in-place не защищён frozen)
        result.data["new"] = "value"
        assert result.data == {"k": "v", "new": "value"}


class TestAgentSandboxResultEquality:
    """Dataclass auto-__eq__."""

    def test_equal_when_same_fields(self) -> None:
        r1 = AgentSandboxResult(success=True, data={"a": 1}, backend="e2b")
        r2 = AgentSandboxResult(success=True, data={"a": 1}, backend="e2b")
        assert r1 == r2

    def test_not_equal_different_success(self) -> None:
        r1 = AgentSandboxResult(success=True, data={}, backend="e2b")
        r2 = AgentSandboxResult(success=False, data={}, backend="e2b")
        assert r1 != r2

    def test_not_equal_different_backend(self) -> None:
        r1 = AgentSandboxResult(success=True, data={}, backend="e2b")
        r2 = AgentSandboxResult(success=True, data={}, backend="pyodide")
        assert r1 != r2

    def test_not_equal_different_data(self) -> None:
        r1 = AgentSandboxResult(success=True, data={"a": 1}, backend="e2b")
        r2 = AgentSandboxResult(success=True, data={"a": 2}, backend="e2b")
        assert r1 != r2


class TestAgentSandboxResultHashing:
    """Frozen dataclass с dict-field — NOT hashable."""

    def test_unhashable_due_to_dict_field(self) -> None:
        result = AgentSandboxResult(success=True, data={}, backend="e2b")
        with pytest.raises(TypeError, match="unhashable"):
            hash(result)


class TestAgentSandboxResultRepr:
    """Dataclass auto __repr__ для debugging."""

    def test_repr_contains_fields(self) -> None:
        result = AgentSandboxResult(success=True, data={"x": 1}, backend="e2b")
        text = repr(result)
        assert "AgentSandboxResult" in text
        assert "success=True" in text
        assert "backend='e2b'" in text


class TestAgentSandboxResultFields:
    """Проверка dataclass-fields."""

    def test_field_names(self) -> None:
        names = {f.name for f in fields(AgentSandboxResult)}
        assert names == {"success", "data", "backend"}


# ── AgentSandbox Protocol ────────────────────────────────────────────


class TestAgentSandboxProtocol:
    """``@runtime_checkable`` Protocol — поддерживает isinstance."""

    def test_duck_typed_satisfies_protocol(self) -> None:
        """Любой класс с правильным ``run_react`` — соответствует Protocol."""

        class FakeSandbox:
            async def run_react(
                self,
                *,
                prompt: str,
                tool_actions: list[str],
                model: str,
                temperature: float,
                durable: bool,
                session_id: str | None,
            ) -> AgentSandboxResult:
                return AgentSandboxResult(
                    success=True,
                    data={"echo": prompt},
                    backend="fake",
                )

        sandbox: AgentSandbox = FakeSandbox()
        result = asyncio.run(
            sandbox.run_react(
                prompt="hello",
                tool_actions=[],
                model="gpt-4",
                temperature=0.7,
                durable=False,
                session_id=None,
            )
        )
        assert result.success is True
        assert result.data == {"echo": "hello"}
        assert result.backend == "fake"

    def test_runtime_checkable_isinstance(self) -> None:
        """``@runtime_checkable`` → ``isinstance`` работает."""

        class GoodSandbox:
            async def run_react(
                self,
                *,
                prompt: str,
                tool_actions: list[str],
                model: str,
                temperature: float,
                durable: bool,
                session_id: str | None,
            ) -> AgentSandboxResult:
                return AgentSandboxResult(
                    success=True, data={}, backend="good"
                )

        class BadSandbox:
            pass

        good = GoodSandbox()
        bad = BadSandbox()
        assert isinstance(good, AgentSandbox)
        assert not isinstance(bad, AgentSandbox)

    def test_missing_method_not_instance(self) -> None:
        """Класс БЕЗ ``run_react`` — НЕ соответствует Protocol."""

        class Incomplete:
            pass

        assert not isinstance(Incomplete(), AgentSandbox)


class TestAgentSandboxProtocolSignature:
    """Проверка сигнатуры ``run_react``: keyword-only args, AgentSandboxResult return."""

    def test_run_react_signature(self) -> None:
        """``run_react`` принимает keyword-only args (после ``*``), возвращает AgentSandboxResult.

        ``self`` — обычный positional-or-keyword параметр instance-метода.
        Все остальные — KEYWORD_ONLY (после ``*`` в сигнатуре).
        """
        import inspect

        sig = inspect.signature(AgentSandbox.run_react)
        params = sig.parameters

        # self — POSITIONAL_OR_KEYWORD, остальные — KEYWORD_ONLY
        assert params["self"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
        non_self = {k: v for k, v in params.items() if k != "self"}
        assert all(p.kind == p.KEYWORD_ONLY for p in non_self.values())

        # Проверка имён
        expected = {
            "prompt",
            "tool_actions",
            "model",
            "temperature",
            "durable",
            "session_id",
        }
        assert set(non_self.keys()) == expected

        # session_id опциональный в реальных реализациях (default None).
        # В самом Protocol ``default`` = ``inspect._empty`` (нет default),
        # потому что Protocol — это contract, не конкретная реализация.
        # Реальные реализации могут задавать ``default=None``.
        import inspect as _inspect

        # Контракт: session_id — Optional (Union со None) — допускает None.
        assert "None" in str(non_self["session_id"].annotation)
