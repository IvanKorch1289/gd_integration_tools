"""Script Runner DSL processor — DISABLED (cycle-6/D-AUDIT-602).

Security model:
- ВНИМАНИЕ: процессор ОТКЛЮЧЁН. Любая попытка выполнить ``script_runner``
  поднимает :class:`NotImplementedError` и логирует RCE-попытку.
- Причина (cycle-4 phase-1 DOMAIN-P0-002): ``script_runner`` шаг исполнял
  произвольный user-supplied код через ``asyncio.create_subprocess_exec``,
  наследуя ``os.environ`` целиком (creds, vault-token протекали в дочерний
  процесс). Default ``allowed_languages=None`` разрешал все 4 интерпретатора
  (``python/node/ruby/shell``) → arbitrary code execution на production-узле.
- Альтернатива (a) AST-validated allowlist не была выбрана потому что
  ``dsl → core.python_ast_sandbox`` ещё не спроектирован; cycle-5/D-AUDIT-502
  в смежном модуле использует тот же подход (NotImplementedError + logger.error)
  при policy_override — синхронизируемся.
- Безопасная замена для бизнес-логики: вынести shell/python вызовы в
  ``extensions/<name>/`` с явным capability ``script_runner.execute`` и
  audit-event. См. ``docs/audit/swarm-2026-08-06/cycle-4/phase-1/06-dsl.md``.

DSL signature и ``to_spec`` сохранены для backward-compat: существующие
routes, импортирующие ``ScriptRunnerProcessor`` (например,
``dsl/builders/ai_rpa/banking_scripts.py``), продолжают компилироваться,
но ``.process()`` всегда падает.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("ScriptRunnerProcessor",)

_logger = get_logger("dsl.processors.script_runner")


class ScriptRunnerProcessor(BaseProcessor):
    """Inline script execution for DSL routes — DISABLED (cycle-6/D-AUDIT-602).

    Usage (legacy, no longer executes)::

        .script_python("print('hello')", timeout=10)

    Все вызовы ``process()`` поднимают :class:`NotImplementedError` с
    RCE-warning в логе. ``__init__`` и ``to_spec`` сохранены для
    backward-compat (импорты и ``pipeline.build()`` продолжают работать).
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
        """Disabled: всегда reject с NotImplementedError (cycle-6/D-AUDIT-602).

        RCE-fix: subprocess-execution удалён. Любой invocation считается
        malicious и логируется с language/length markers для audit.
        Pipeline не падает с unhandled exception: ExecutionEngine ловит
        ``Exception`` и переводит exchange в ``failed`` (см.
        ``src/backend/dsl/engine/execution_engine.py:294-308``).
        """
        code_len = len(self._code)
        _logger.error(
            "script_runner_disabled: language=%s code_len=%d allowed=%s "
            "(cycle-6/D-AUDIT-602 RCE fix)",
            self._language,
            code_len,
            sorted(self._allowed) if self._allowed else None,
        )
        raise NotImplementedError(
            "ScriptRunnerProcessor disabled (cycle-6/D-AUDIT-602): "
            "arbitrary subprocess execution exposes RCE on production routes. "
            "Move shell/python scripts to extensions/<name>/ with "
            "explicit capability 'script_runner.execute' and audit-event.",
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Serialize to YAML-compatible spec (kept for round-trip)."""
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
