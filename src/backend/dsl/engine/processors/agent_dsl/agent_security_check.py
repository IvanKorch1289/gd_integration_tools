"""Agent Security Check DSL processor (S187).

DSL wrapper для :class:`AgentSecurityFramework`. Позволяет declarative
policy в route.yaml::

    - agent_security_check:
        check: "prompt"
        value: "${body.prompt}"
        on_violation: "block"   # block | warn | allow

    - agent_security_check:
        check: "command"
        value: "rm -rf /"
        on_violation: "block"

    - agent_security_check:
        check: "file"
        value: "/etc/passwd"
        on_violation: "block"

    - agent_security_check:
        check: "sql"
        value: "DROP DATABASE"
        on_violation: "block"

Capabilities:
- ``agent.security.check`` — для audit emission

Side effects:
- exchange.properties["agent_security_decision"] = SecurityDecision
- При block — exchange.fail() с reason
- При warn — log warning, continue
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from src.backend.core.ai.security import SecurityDecision
from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("AgentSecurityCheckProcessor",)

_logger = get_logger("dsl.agent_security_check")

from src.backend.dsl.registry import processor  # D-AGENTS-P1-002 fix (cycle 26)

CheckType = Literal["prompt", "command", "sql", "file"]


@processor(
    "agent_security_check",
    namespace="core",
    capabilities=("agent.security.check",),
    spec_schema={
        "type": "object",
        "properties": {
            "policy": {"type": "string"},
            "action_on_deny": {"enum": ["block", "warn", "log"]},
        },
        "required": ["policy"],
    },
    meta={"tier": 1, "category": "agent"},
)
class AgentSecurityCheckProcessor(BaseProcessor):
    """DSL processor для Agent Security Framework (S187).

    Usage (Python)::

        builder.agent_security_check(
            check="prompt",
            value="${body.user_input}",
            on_violation="block",
        )

    Usage (YAML)::

        - agent_security_check:
            check: prompt
            value: ${body.user_input}
            on_violation: block

    Side effects:
        exchange.properties["agent_security_decision"] = SecurityDecision
        При block — exchange.fail() с reason
        При warn — log warning, continue
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        check: CheckType,
        value: str,
        on_violation: Literal["block", "warn", "allow"] = "block",
        file_size_bytes: int = 0,
        name: str | None = None,
    ) -> None:
        """Инициализация DSL security check processor.

        Args:
            check: Тип проверки (``"prompt"`` / ``"command"`` / ``"sql"`` / ``"file"``).
            value: Значение для проверки.
            on_violation: Поведение при нарушении (``"block"`` / ``"warn"`` / ``"allow"``).
            file_size_bytes: Размер файла (для ``check="file"``).
            name: Имя процессора.
        """
        super().__init__(name=name or f"agent_security_check[{check}]")
        self._check = check
        self._value = value
        self._on_violation = on_violation
        self._file_size_bytes = file_size_bytes

    @handle_processor_error
    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext,
    ) -> None:
        """Выполнить security check.

        Side effects:
            exchange.properties["agent_security_decision"] = SecurityDecision
            При block: exchange.fail()
        """
        # Cycle 4b swarm (D418 real): cap value length to prevent
        # abuse via oversized security-check inputs (potential DoS via
        # huge file_path or prompt string). The actual security check
        # is delegated to AgentSecurity facade; this is just a defensive
        # cap at the DSL boundary.
        if self._value and len(self._value) > 100_000:  # 100KB
            # Cycle 77 L3: use module-level canonical logger.
            _logger.warning(
                "%s: value truncated from %d to 100000 chars (S227 cycle 4 hardening)",
                self.name, len(self._value),
            )
            self._value = self._value[:100_000]

        try:
            from src.backend.services.agent_security.facade import (
                get_agent_security_facade,
            )

            facade = get_agent_security_facade()

            # Dispatch по типу
            if self._check == "prompt":
                decision = facade.validate_prompt(self._value)
            elif self._check == "command":
                decision = facade.validate_command(self._value)
            elif self._check == "sql":
                decision = facade.validate_sql(self._value)
            elif self._check == "file":
                decision = facade.validate_file_modification(
                    self._value, file_size_bytes=self._file_size_bytes,
                )
            else:
                decision = SecurityDecision(
                    allowed=True,
                    reason=f"unknown_check_type: {self._check}",
                )

            # Store decision в exchange
            exchange.set_property("agent_security_decision", decision)

            # Apply on_violation policy
            if not decision.allowed:
                _logger.warning(
                    "agent_security_check violation: check=%s threat=%s reason=%s",
                    self._check,
                    decision.threat_level,
                    decision.reason,
                )

                if self._on_violation == "block":
                    exchange.fail(
                        f"agent_security.{self._check}_blocked: {decision.reason}",
                    )
                elif self._on_violation == "warn":
                    _logger.warning(
                        "agent_security.%s_warn: %s",
                        self._check,
                        decision.reason,
                    )
                # "allow" → continue regardless

        except Exception as exc:
            _logger.warning(
                "agent_security_check failed for %s: %s",
                self._check,
                exc,
            )
            if self._on_violation == "block":
                exchange.fail(f"agent_security_check_error: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфиг процессора в JSON-Schema spec."""
        spec: dict[str, Any] = {
            "type": "agent_security_check",
            "check": self._check,
            "value": self._value,
            "on_violation": self._on_violation,
        }
        if self._check == "file":
            spec["file_size_bytes"] = self._file_size_bytes
        return spec
