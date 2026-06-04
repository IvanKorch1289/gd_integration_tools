"""Tests for src.backend.services.execution.action_dispatcher."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.interfaces.action_dispatcher import (
    ActionCommandSchema,
    ActionError,
    ActionResult,
    DispatchContext,
)
from src.backend.services.execution.action_dispatcher import (
    DefaultActionDispatcher,
    get_action_dispatcher,
)


@pytest.mark.unit
class TestDefaultActionDispatcher:
    """Tests for DefaultActionDispatcher."""

    @pytest.fixture
    def registry(self) -> MagicMock:
        reg = MagicMock()
        reg.is_registered.return_value = True
        reg.list_middleware.return_value = []
        return reg

    @pytest.fixture
    def dispatcher(self, registry: MagicMock) -> DefaultActionDispatcher:
        return DefaultActionDispatcher(registry=registry)

    @pytest.mark.asyncio
    async def test_dispatch_with_schema_no_context(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        registry.dispatch = AsyncMock(return_value={"data": 123})
        command = ActionCommandSchema(action="test", payload={})
        result = await dispatcher.dispatch(command)
        assert result == {"data": 123}
        registry.dispatch.assert_awaited_once_with(command)

    @pytest.mark.asyncio
    async def test_dispatch_with_schema_and_context_success(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        registry.dispatch = AsyncMock(return_value={"data": 123})
        command = ActionCommandSchema(action="test", payload={})
        ctx = DispatchContext()
        result = await dispatcher.dispatch(command, context=ctx)
        assert result == {"data": 123}

    @pytest.mark.asyncio
    async def test_dispatch_with_schema_and_context_action_not_found(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        async def _dispatch(cmd: ActionCommandSchema) -> Any:
            raise KeyError(cmd.action)

        registry.dispatch = _dispatch
        command = ActionCommandSchema(action="missing", payload={})
        ctx = DispatchContext()
        with pytest.raises(KeyError):
            await dispatcher.dispatch(command, context=ctx)

    @pytest.mark.asyncio
    async def test_dispatch_with_schema_and_context_dispatch_failed(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        async def _dispatch(cmd: ActionCommandSchema) -> Any:
            raise RuntimeError("broken")

        registry.dispatch = _dispatch
        command = ActionCommandSchema(action="test", payload={})
        ctx = DispatchContext()
        with pytest.raises(RuntimeError, match="broken"):
            await dispatcher.dispatch(command, context=ctx)

    @pytest.mark.asyncio
    async def test_dispatch_action_gateway_not_registered(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        registry.is_registered.return_value = False
        result = await dispatcher.dispatch_action("missing", {}, DispatchContext())
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "action_not_found"

    @pytest.mark.asyncio
    async def test_dispatch_action_success(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        registry.dispatch = AsyncMock(return_value={"ok": True})
        result = await dispatcher.dispatch_action("test", {}, DispatchContext())
        assert result.success is True
        assert result.data == {"ok": True}

    @pytest.mark.asyncio
    async def test_dispatch_action_keyerror_in_terminal(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        async def _dispatch(cmd: ActionCommandSchema) -> Any:
            raise KeyError(cmd.action)

        registry.dispatch = _dispatch
        result = await dispatcher.dispatch_action("test", {}, DispatchContext())
        assert result.success is False
        assert result.error.code == "action_not_found"

    @pytest.mark.asyncio
    async def test_dispatch_action_exception_in_terminal(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        async def _dispatch(cmd: ActionCommandSchema) -> Any:
            raise ValueError("boom")

        registry.dispatch = _dispatch
        result = await dispatcher.dispatch_action("test", {}, DispatchContext())
        assert result.success is False
        assert result.error.code == "dispatch_failed"

    def test_is_registered(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        registry.is_registered.return_value = True
        assert dispatcher.is_registered("test") is True

    def test_list_actions(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        registry.list_actions.return_value = ("a", "b")
        assert dispatcher.list_actions() == ("a", "b")

    def test_list_actions_by_transport(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        meta = MagicMock()
        meta.action = "a"
        registry.list_metadata.return_value = (meta,)
        assert dispatcher.list_actions("rest") == ("a",)

    def test_list_metadata(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        registry.list_metadata.return_value = ()
        assert dispatcher.list_metadata() == ()

    def test_register_middleware(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        mw = MagicMock()
        dispatcher.register_middleware(mw)
        registry.register_middleware.assert_called_once_with(mw)

    def test_get_metadata(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        meta = MagicMock()
        registry.get_metadata.return_value = meta
        assert dispatcher.get_metadata("test") is meta

    @pytest.mark.asyncio
    async def test_middleware_chain_executed(
        self, dispatcher: DefaultActionDispatcher, registry: MagicMock
    ) -> None:
        calls: list[str] = []

        class MW:
            def __init__(self, name: str) -> None:
                self.name = name

            async def __call__(
                self, action: str, payload: Any, ctx: DispatchContext, next_handler: Any
            ) -> ActionResult:
                calls.append(f"before_{self.name}")
                result = await next_handler(action, payload, ctx)
                calls.append(f"after_{self.name}")
                return result

        registry.list_middleware.return_value = [MW("a"), MW("b")]
        registry.dispatch = AsyncMock(return_value={"ok": True})

        await dispatcher.dispatch_action("test", {}, DispatchContext())
        assert calls == ["before_a", "before_b", "after_b", "after_a"]

    def test_singleton_get_action_dispatcher(self) -> None:
        d1 = get_action_dispatcher()
        d2 = get_action_dispatcher()
        assert d1 is d2
