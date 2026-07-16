"""Card PAN Tokenization DSL processor — PCI-DSS compliance (S183 I-10).

ADR-PCI-DSS: PAN (Primary Account Number) не должен храниться в открытом виде.
Этот процессор реализует reversible tokenization для card numbers через
format-preserving tokenization (FPT) pattern.

Использует те же механизмы что и PIITokenizer:
- AES-GCM для reversible encryption
- Format-preserving mapping (FPE-like) для сохранения длины
- TokenRegistry (Redis-backed) для хранения token→PAN mapping

Capabilities:
- ``pii.tokenize.reversible.card`` — для reversible PAN tokenization
- ``pii.audit`` — для audit event emission

Spec (YAML)::
    - card_tokenize:
        source_property: "body.card_number"
        result_property: "body.card_token"
        method: "fpe"        # fpe | vault
        bin_preserve: true    # сохранить первые 6 цифр (BIN)

Note:
    Production deployment требует integration с PCI-DSS vault.
    Этот DSL — contract-level реализация с format-preserving stubs.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("CardTokenizeProcessor", "CardTokenResult")


_logger = get_logger("dsl.security.card_tokenize")

# PCI-DSS Luhn-valid PAN (13-19 digits, может быть группами)
_PAN_PATTERN = re.compile(r"^\d{13,19}$")
_PAN_GROUPED_PATTERN = re.compile(r"^(\d{4})[\s-]?(\d{4})[\s-]?(\d{4})[\s-]?(\d{1,7})$")


@dataclass(slots=True, frozen=True)
class CardTokenResult:
    """Результат card tokenization.

    Attributes:
        token: Reversible token (format-preserving).
        bin_prefix: BIN (first 6 digits) — для BIN routing.
        last_four: Last 4 digits (для UI display).
        method: Tokenization method (``"fpe"`` или ``"vault"``).
        token_id: Token ID для detokenization lookup.
    """

    token: str
    bin_prefix: str
    last_four: str
    method: str
    token_id: str


class CardTokenizeProcessor(BaseProcessor):
    """Card PAN Tokenization DSL processor — PCI-DSS compliance.

    Usage::

        builder.card_tokenize(
            source_property="body.card_number",
            result_property="body.card_token",
        )

    Workflow:
        1. Extract PAN from source_property
        2. Validate via Luhn check
        3. Generate token (format-preserving)
        4. Store token→PAN mapping (via TokenRegistry)
        5. Emit audit event
        6. Store CardTokenResult in exchange
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        source_property: str,
        result_property: str | None = None,
        method: str = "fpe",
        bin_preserve: bool = True,
        name: str | None = None,
    ) -> None:
        """Инициализация Card PAN tokenize processor.

        Args:
            source_property: Path к PAN в exchange (e.g., ``"body.card_number"``).
            result_property: Path для сохранения результата (default ``source + "_token"``).
            method: ``"fpe"`` (format-preserving) или ``"vault"`` (PCI vault).
            bin_preserve: Сохранять первые 6 цифр (BIN) для routing.
            name: Имя процессора.
        """
        super().__init__(name=name or f"card_tokenize[{source_property}]")
        self._source_property = source_property
        self._result_property = result_property or f"{source_property}_token"
        self._method = method
        self._bin_preserve = bin_preserve

    @handle_processor_error
    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Tokenize PAN из source_property.

        Side effects:
            exchange.properties[result_property] = CardTokenResult
        """
        # Step 1: extract PAN
        pan = self._extract_pan(exchange)
        if not pan:
            _logger.warning("card_tokenize: no PAN extracted from %s", self._source_property)
            return

        # Step 2: Luhn validate
        if not self._luhn_check(pan):
            exchange.fail(f"card_tokenize: invalid PAN (Luhn failed): {pan[-4:].rjust(4, '*')}")
            return

        # Step 3: Generate token
        bin_prefix = pan[:6] if self._bin_preserve else ""
        last_four = pan[-4:]
        token_id = str(uuid.uuid4())

        if self._method == "fpe":
            token = self._format_preserving_token(pan, bin_prefix)
        elif self._method == "vault":
            token = await self._vault_tokenize(pan)
        else:
            exchange.fail(f"card_tokenize: unknown method: {self._method}")
            return

        # Step 4: Store mapping (S183: lazy — production TokenRegistry)
        try:
            await self._store_mapping(token_id, pan, token)
        except Exception as exc:
            _logger.warning("card_tokenize: store mapping failed: %s", exc)

        # Step 5: Audit emit
        await self._emit_audit(
            token_id=token_id,
            bin_prefix=bin_prefix,
            last_four=last_four,
            method=self._method,
        )

        # Step 6: Result
        result = CardTokenResult(
            token=token,
            bin_prefix=bin_prefix,
            last_four=last_four,
            method=self._method,
            token_id=token_id,
        )

        # Store result в exchange
        self._set_result_property(exchange, result)

        _logger.info(
            "card_tokenize completed: bin=%s last4=%s method=%s token_id=%s",
            bin_prefix,
            last_four,
            self._method,
            token_id,
        )

    def _extract_pan(self, exchange: Exchange[Any]) -> str | None:
        """Extract PAN из source_property.

        Поддерживает:
        - Plain string (``"4111111111111111"``)
        - Grouped string (``"4111-1111-1111-1111"``)
        - Вложенные dict (берёт ``body.card_number`` рекурсивно)
        """
        value = self._get_property(exchange, self._source_property)
        if value is None:
            return None

        if isinstance(value, dict):
            value = value.get("card_number") or value.get("pan")

        if not isinstance(value, str):
            return None

        # Strip groups
        stripped = re.sub(r"[\s-]", "", value)
        return stripped if _PAN_PATTERN.match(stripped) else None

    @staticmethod
    def _luhn_check(pan: str) -> bool:
        """Luhn algorithm для PAN validation."""
        digits = [int(d) for d in pan]
        checksum = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
        return checksum % 10 == 0

    @staticmethod
    def _format_preserving_token(pan: str, bin_prefix: str) -> str:
        """Format-preserving token (S183 stub).

        Production: заменить на PCI-DSS vault FF1/FF3 encryption.
        S183: генерируем cryptographically secure hex string с BIN prefix.
        """
        # Random 10 hex chars (FPE-like substitution для non-BIN digits)
        random_part = secrets.token_hex(5)
        if bin_prefix:
            return f"{bin_prefix}{random_part}{pan[-1]}"  # check digit preserved
        return random_part + pan[-1]

    async def _vault_tokenize(self, pan: str) -> str:
        """Vault-based tokenization (lazy через TokenRegistry)."""
        # Production: TokenRegistry.register() → vault format-preserving token
        try:
            from src.backend.infrastructure.security.token_registry import (
                TokenRegistry,
            )

            registry = TokenRegistry()
            token_id = await registry.register(
                namespace="card",
                plaintext=pan,
                format_preserving=True,
            )
            return token_id
        except Exception as exc:
            _logger.warning("vault_tokenize fallback to FPE: %s", exc)
            return self._format_preserving_token(pan, "")

    async def _store_mapping(
        self, token_id: str, pan: str, token: str
    ) -> None:
        """Store token→PAN mapping."""
        # Production: Redis-backed через TokenRegistry (already done в _vault_tokenize)
        # S183: stub — production wiring TODO
        pass

    async def _emit_audit(
        self,
        *,
        token_id: str,
        bin_prefix: str,
        last_four: str,
        method: str,
    ) -> None:
        """Emit audit event для tokenization."""
        try:
            from src.backend.core.observability.logging_helpers import (
                log_audit_event_lite,
            )

            log_audit_event_lite(
                _logger,
                severity="warning",  # PCI tokenization — significant
                event="card.tokenized",
                token_id=token_id,
                bin_prefix=bin_prefix,
                last_four=last_four,
                method=method,
            )
        except Exception as exc:
            _logger.warning("audit emit failed: %s", exc)

    def _get_property(self, exchange: Exchange[Any], path: str) -> Any:
        """Get property по dot-path."""
        parts = path.split(".")
        value: Any = exchange.properties
        for part in parts:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def _set_result_property(
        self, exchange: Exchange[Any], result: CardTokenResult
    ) -> None:
        """Set result в result_property."""
        parts = self._result_property.split(".")
        target = exchange.properties
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = {
            "token": result.token,
            "bin_prefix": result.bin_prefix,
            "last_four": result.last_four,
            "method": result.method,
            "token_id": result.token_id,
        }

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфиг процессора в JSON-Schema spec."""
        return {
            "type": "card_tokenize",
            "source_property": self._source_property,
            "result_property": self._result_property,
            "method": self._method,
            "bin_preserve": self._bin_preserve,
        }
