"""P0 regression test (Cycle 35, production-grade plan).

``InvocationRequest`` теперь имеет ``principal``/``permissions`` поля,
которые прокидываются в ``ActionCommandSchema.meta`` через
``run_mixin._run_silent`` / ``run_mixin._run_and_stream`` /
``invoke_modes_mixin._invoke_sync``.

Pre-fix: InvocationRequest не имел auth context → ActionCommandSchema
создавался с anonymous principal/permissions → Tier-1/2 actions
теряли auth context.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/services/execution/test_invocation_request_principal.py -v
"""

from __future__ import annotations

from src.backend.core.interfaces.invoker import InvocationMode, InvocationRequest


class TestInvocationRequestPrincipal:
    """Cycle 35: InvocationRequest.principal + permissions defaults."""

    def test_default_principal_empty(self) -> None:
        """``InvocationRequest(action='x')`` → principal='', permissions=()."""
        req = InvocationRequest(action="x")
        assert req.principal == "", "Default principal должен быть пустым"
        assert req.permissions == (), "Default permissions должен быть пустым"

    def test_with_principal(self) -> None:
        """``InvocationRequest(action='x', principal='alice', permissions=(...))``."""
        req = InvocationRequest(
            action="x",
            principal="alice",
            permissions=("read:orders", "write:orders"),
        )
        assert req.principal == "alice"
        assert req.permissions == ("read:orders", "write:orders")

    def test_with_mode_and_principal(self) -> None:
        """``InvocationRequest`` с mode + principal комбинируется правильно."""
        req = InvocationRequest(
            action="x",
            mode=InvocationMode.BACKGROUND,
            principal="carol",
        )
        assert req.mode == InvocationMode.BACKGROUND
        assert req.principal == "carol"
        assert req.permissions == ()
