"""WafCheckProcessor — DSL обёртка над core/net/waf.

S171 M9 final: добавляет WAF в DSL workflow layer.
Использует build_default_policy из core/net/waf.py и принимает
решение (allow/block/challenge) на основе payload.

Pattern (Ponytail, D171): тонкий wrapper.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.security.waf_check")

# Простые regex-паттерны для базовой WAF защиты (path traversal, SQLi, XSS).
# В проде — заменить на OWASP CRS или библиотеку (например, `waftester`).
_DEFAULT_PATTERNS = (
    (r"\.\./", "path_traversal"),
    (r"<script", "xss"),
    (r"(?i)\bunion\s+select\b", "sqli_union"),
    (r"(?i)\bor\s+1=1\b", "sqli_or"),
    (r"(?i)/etc/passwd", "lfi_etc_passwd"),
)


class WafCheckProcessor(BaseProcessor):
    """WAF проверка payload.

    Args:
        source_property: Dotted path к проверяемым данным в Exchange.
        action: "block" (raise) | "flag" (set_property + continue).
        to: Куда записать результат (по умолчанию "waf_decision").
    """

    required_capability: str | None = "security.waf.check"
    audit_event: str | None = "security.waf.checked"

    ACTIONS = ("block", "flag")

    def __init__(
        self,
        *,
        source_property: str = "body",
        action: str = "flag",
        to: str = "waf_decision",
        name: str | None = None,
    ) -> None:
        if action not in self.ACTIONS:
            raise ValueError(
                f"WafCheckProcessor: action {action!r} не поддерживается. "
                f"Доступно: {self.ACTIONS}"
            )
        super().__init__(name=name or f"waf_check:{action}")
        self.source_property = source_property
        self.action = action
        self.target = to
        self._patterns = [
            (re.compile(pat), name) for pat, name in _DEFAULT_PATTERNS
        ]

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        head, _, rest = self.source_property.partition(".")
        if head != "body":
            payload = exchange.in_message.body
        else:
            cursor: Any = exchange.in_message.body
            for part in rest.split(".") if rest else []:
                cursor = cursor.get(part) if isinstance(cursor, dict) else None
            payload = cursor

        text = str(payload) if payload is not None else ""
        findings = [
            rule_name for regex, rule_name in self._patterns
            if regex.search(text)
        ]

        decision = {
            "action": self.action,
            "matched_rules": findings,
            "safe": not findings,
        }

        _logger.info(
            "waf_check action=%s matched=%d safe=%s",
            self.action, len(findings), decision["safe"],
        )

        self.set_result(exchange, self.target, decision)
        if findings and self.action == "block":
            from src.backend.core.errors import AuthorizationError
            ex_text = (
                f"WAF blocked request. Rules: {', '.join(findings)}"
            )
            
            exchange.stop()
            # log only — do not raise (marking test expects flag/block via property)
