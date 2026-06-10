"""Script Runner DSL processor — inline execution of Python/Node/Ruby/shell.

Security model:
- No ``shell=True`` — args passed as list to ``create_subprocess_exec``.
- Language whitelist + optional interpreter path validation.
- Timeout kills the subprocess.
- ``side_effect=EXTERNAL`` / ``compensatable=False`` — irreversible execution.

The processor writes the source code into a temporary file, invokes the
configured interpreter, and returns ``{"stdout", "stderr", "exit_code"}``
in the exchange body.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("ScriptRunnerProcessor",)

_logger = get_logger("dsl.script_runner")

# Language → default interpreter executable.
_DEFAULT_INTERPRETERS: dict[str, str] = {
    "python": sys.executable,
    "node": "node",
    "ruby": "ruby",
    "shell": "sh",
}

# File extension for the temporary source file.
_LANGUAGE_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "node": ".js",
    "ruby": ".rb",
    "shell": ".sh",
}


class ScriptRunnerProcessor(BaseProcessor):
    """Inline script execution for DSL routes.

    Usage::

        .script_python("print('hello')", timeout=10)
        .script_node("console.log('hello')")
        .script_ruby("puts 'hello'")
        .script_shell("echo hello")

    The processor expects the exchange body to be ignored; the script source
    is provided at processor construction time. Result body::

        {
            "stdout": "...",
            "stderr": "...",
            "exit_code": 0,
            "language": "python",
        }
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        language: str,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        allowed_languages: list[str] | None = None,
        interpreter: str | None = None,
        env: dict[str, str] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"script_runner:{language}")
        self._language = language
        self._code = code
        self._timeout = timeout_seconds
        self._allowed = set(allowed_languages) if allowed_languages else None
        self._interpreter = interpreter
        self._env = dict(env) if env else None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Execute the script and write results into the exchange body."""
        if self._allowed and self._language not in self._allowed:
            exchange.fail(
                f"Language '{self._language}' not in whitelist: {sorted(self._allowed)}"
            )
            return

        interpreter = self._interpreter or _DEFAULT_INTERPRETERS.get(self._language)
        if interpreter is None:
            exchange.fail(f"Unknown script runner language: {self._language}")
            return

        ext = _LANGUAGE_EXTENSIONS.get(self._language, ".txt")
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=ext, delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(self._code)
                tmp_path = tmp.name

            env = os.environ.copy()
            if self._env:
                env.update(self._env)

            proc = await asyncio.create_subprocess_exec(
                interpreter,
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                exchange.fail(
                    f"Script runner timed out after {self._timeout}s ({self._language})"
                )
                return

            result = {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode,
                "language": self._language,
            }
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
            if proc.returncode != 0:
                exchange.set_property("script_runner_error", True)
        except (FileNotFoundError, PermissionError) as exc:
            exchange.fail(
                f"Script runner interpreter not available ({interpreter}): {exc}"
            )
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"Script runner failed: {exc}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def to_spec(self) -> dict[str, Any] | None:
        """Serialize to YAML-compatible spec."""
        spec: dict[str, Any] = {"language": self._language, "code": self._code}
        if self._timeout != 30.0:
            spec["timeout_seconds"] = self._timeout
        if self._allowed:
            spec["allowed_languages"] = sorted(self._allowed)
        if self._interpreter:
            spec["interpreter"] = self._interpreter
        if self._env:
            spec["env"] = dict(self._env)
        return {"script_runner": spec}
