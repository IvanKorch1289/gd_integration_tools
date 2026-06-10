"""Unit-тесты для ScriptRunnerProcessor (Sprint 42).

Tests cover:
- successful python execution with stdout/stderr capture
- non-zero exit code handling
- language whitelist enforcement
- timeout handling
- missing interpreter handling
- builder methods (script_python / script_node / script_ruby / script_shell)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.script_runner import ScriptRunnerProcessor


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


def _mock_process(stdout: bytes, stderr: bytes, returncode: int) -> MagicMock:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


class TestScriptRunnerProcessor:
    """Tests for ScriptRunnerProcessor."""

    @pytest.mark.asyncio
    async def test_python_runs_and_captures_output(self) -> None:
        proc = ScriptRunnerProcessor(language="python", code="print('hi')")
        exchange = _make_exchange()

        mock_proc = _mock_process(b"hi\n", b"", 0)

        with (
            patch(
                "src.backend.dsl.engine.processors.script_runner.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_proc),
            ),
            patch(
                "src.backend.dsl.engine.processors.script_runner.tempfile.NamedTemporaryFile"
            ) as mock_tmp,
            patch(
                "src.backend.dsl.engine.processors.script_runner.os.unlink"
            ) as mock_unlink,
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/fake.py"
            mock_tmp.return_value.__enter__.return_value = mock_file
            await proc.process(exchange, MagicMock())

        assert exchange.out_message is not None
        body: dict[str, Any] | None = exchange.out_message.body
        assert body is not None
        assert body["stdout"] == "hi\n"
        assert body["stderr"] == ""
        assert body["exit_code"] == 0
        assert body["language"] == "python"
        mock_unlink.assert_called_once_with("/tmp/fake.py")

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_sets_error_property(self) -> None:
        proc = ScriptRunnerProcessor(language="python", code="raise SystemExit(1)")
        exchange = _make_exchange()

        mock_proc = _mock_process(b"", b"error", 1)

        with (
            patch(
                "src.backend.dsl.engine.processors.script_runner.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_proc),
            ),
            patch(
                "src.backend.dsl.engine.processors.script_runner.tempfile.NamedTemporaryFile"
            ) as mock_tmp,
            patch("src.backend.dsl.engine.processors.script_runner.os.unlink"),
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/fake.py"
            mock_tmp.return_value.__enter__.return_value = mock_file
            await proc.process(exchange, MagicMock())

        assert exchange.out_message is not None
        body = exchange.out_message.body
        assert body is not None
        assert body["exit_code"] == 1
        assert exchange.properties.get("script_runner_error") is True

    @pytest.mark.asyncio
    async def test_language_not_in_whitelist_fails(self) -> None:
        proc = ScriptRunnerProcessor(
            language="ruby", code="puts 'hi'", allowed_languages=["python", "node"]
        )
        exchange = _make_exchange()

        await proc.process(exchange, MagicMock())

        assert exchange.status.name == "failed"
        assert exchange.error is not None
        assert "not in whitelist" in exchange.error

    @pytest.mark.asyncio
    async def test_unknown_language_fails(self) -> None:
        proc = ScriptRunnerProcessor(language="rust", code="fn main() {}")
        exchange = _make_exchange()

        with patch("src.backend.dsl.engine.processors.script_runner.os.unlink"):
            await proc.process(exchange, MagicMock())

        assert exchange.status.name == "failed"
        assert exchange.error is not None
        assert "Unknown script runner language" in exchange.error

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self) -> None:
        proc = ScriptRunnerProcessor(
            language="python", code="import time; time.sleep(100)", timeout_seconds=1.0
        )
        exchange = _make_exchange()

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_proc.wait = AsyncMock(return_value=0)

        with (
            patch(
                "src.backend.dsl.engine.processors.script_runner.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_proc),
            ),
            patch(
                "src.backend.dsl.engine.processors.script_runner.tempfile.NamedTemporaryFile"
            ) as mock_tmp,
            patch("src.backend.dsl.engine.processors.script_runner.os.unlink"),
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/fake.py"
            mock_tmp.return_value.__enter__.return_value = mock_file
            await proc.process(exchange, MagicMock())

        assert exchange.status.name == "failed"
        assert exchange.error is not None
        assert "timed out" in exchange.error
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_interpreter_fails(self) -> None:
        proc = ScriptRunnerProcessor(language="node", code="console.log('hi')")
        exchange = _make_exchange()

        with (
            patch(
                "src.backend.dsl.engine.processors.script_runner.asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError,
            ),
            patch(
                "src.backend.dsl.engine.processors.script_runner.tempfile.NamedTemporaryFile"
            ) as mock_tmp,
            patch("src.backend.dsl.engine.processors.script_runner.os.unlink"),
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/fake.js"
            mock_tmp.return_value.__enter__.return_value = mock_file
            await proc.process(exchange, MagicMock())

        assert exchange.status.name == "failed"
        assert exchange.error is not None
        assert "interpreter not available" in exchange.error

    def test_to_spec_serializes_config(self) -> None:
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
            }
        }

    def test_to_spec_omits_defaults(self) -> None:
        proc = ScriptRunnerProcessor(language="shell", code="echo hi")
        spec = proc.to_spec()
        assert spec == {"script_runner": {"language": "shell", "code": "echo hi"}}


class TestScriptRunnerBuilder:
    """Smoke tests for builder methods added to AIRPAMixin."""

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
