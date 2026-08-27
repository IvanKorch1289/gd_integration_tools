"""P4 regression test (Cycle 16, production-grade plan).

SshCommandProcessor теперь имеет capability-gate parity с
TerminalExecProcessor: ``required_capability`` + ``audit_event`` ClassVar
+ ``auth_check`` в process().

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/dsl/engine/processors/test_ssh_command_capability.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.processors.ssh_command import SshCommandProcessor


class TestSshCommandCapabilityParity:
    """Cycle 16: capability-gate + audit parity с TerminalExecProcessor."""

    def test_required_capability_classvar(self) -> None:
        """``SshCommandProcessor.required_capability = 'rpa.shell.exec'``."""
        assert (
            SshCommandProcessor.required_capability == "rpa.shell.exec"
        ), (
            f"Expected 'rpa.shell.exec', got {SshCommandProcessor.required_capability!r}"
        )

    def test_audit_event_classvar(self) -> None:
        """``SshCommandProcessor.audit_event = 'rpa.shell.exec'``."""
        assert (
            SshCommandProcessor.audit_event == "rpa.shell.exec"
        ), (
            f"Expected 'rpa.shell.exec', got {SshCommandProcessor.audit_event!r}"
        )

    def test_capability_matches_shell_exec(self) -> None:
        """Parity с TerminalExecProcessor — same capability name."""
        from src.backend.dsl.engine.processors.rpa.system import TerminalExecProcessor

        assert (
            TerminalExecProcessor.required_capability
            == SshCommandProcessor.required_capability
        ), "SSH и Terminal должны иметь одинаковый capability"

    @pytest.mark.asyncio
    async def test_auth_check_called_in_process(self) -> None:
        """``process`` вызывает ``self.auth_check(exchange, action='execute')``."""
        proc = SshCommandProcessor(host="test.example.com", command="ls")

        # Mock auth_check для верификации вызова
        auth_called_with: list[tuple[str, ...]] = []

        async def fake_auth_check(exchange: object, action: str) -> bool:
            auth_called_with.append((action,))
            return False  # не прошёл — process возвращает без ошибки

        proc.auth_check = fake_auth_check  # type: ignore[method-assign]

        exchange = MagicMock()
        context = MagicMock()

        # process должен early-return (auth_check = False) без exception
        await proc.process(exchange, context)

        assert auth_called_with == [("execute",)], (
            f"auth_check НЕ вызван с action='execute': {auth_called_with}"
        )
