"""DLQ replay governance — управляемая модель replay для DLQ (W11 P1-2, ADR-0339).

Стратегический анализ 2026-09-22 (timestamp 1790089356160) выявил gap:

> «DLQ без безопасного replay становится накопителем ошибок. Следует добавить
> управляемую модель:
>
>     inspect → classify → redact → dry-run → replay → verify → archive
>
> Replay должен требовать capability, поддерживать ограничение скорости и
> автоматически сохранять исходный event ID, replay ID и причину оператора.»

Этот модуль реализует 7-шаговый flow + governance hooks (capability, rate
limit, audit, dry-run). Построен поверх существующего
:class:`src.backend.infrastructure.messaging.dlq_base.DLQEnvelope`.

Использование::

    governor = DLQReplayGovernor(
        rate_limit_per_minute=10,
        capability_check=lambda cap, ctx: check_capability(cap),
        audit_writer=audit_log,
    )

    # 1. Inspect
    snapshot = governor.inspect(envelope)

    # 2. Classify
    classification = governor.classify(envelope)

    # 3. Redact (PII)
    redacted = governor.redact(envelope)

    # 4. Dry-run (no side-effects)
    dry_result = governor.replay(envelope, dry_run=True, operator_id="alice")

    # 5. Real replay (capability + rate-limit + audit)
    result = governor.replay(envelope, dry_run=False, operator_id="alice", reason="ops-incident-42")

    # 6. Verify
    governor.verify(replay_id=result.replay_id, success=True)

    # 7. Archive
    governor.archive(envelope)

Инварианты:
- Replay без capability → ``CapabilityDeniedError`` (fail-closed).
- Превышение rate limit → ``RateLimitExceeded`` (без side-effects).
- Audit trail: каждый replay создаёт запись с (replay_id, operator_id,
  original_event_id, reason, correlation_id, timestamp).
- Dry-run mode: всё считается, но НЕ отправляется (no broker.publish).
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

# DLQEnvelope импортируется лениво чтобы избежать циклических импортов
# (services/ops → infrastructure/messaging). Type hint через TYPE_CHECKING.
from typing import TYPE_CHECKING, Any, Callable, Mapping
from uuid import uuid4

if TYPE_CHECKING:
    from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = (
    "DLQClassification",
    "DLQReplayGovernor",
    "DLQReplayResult",
    "ReplayAuditEntry",
    "ReplayStep",
    "SensitivityLevel",
)


class ReplayStep(StrEnum):
    """7 шагов DLQ replay governance (per strategic analysis 2026-09-22).

    Flow: ``inspect → classify → redact → dry_run → replay → verify → archive``.
    """

    INSPECT = "inspect"
    CLASSIFY = "classify"
    REDACT = "redact"
    DRY_RUN = "dry_run"
    REPLAY = "replay"
    VERIFY = "verify"
    ARCHIVE = "archive"


class SensitivityLevel(StrEnum):
    """Уровень чувствительности payload'а (для redaction + access policy)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"
    FINANCIAL = "financial"
    SECRET_TIER = "secret"  # noqa: S105 — enum value, не password


# ──────────────────── Data classes ────────────────────


@dataclass(frozen=True, slots=True)
class DLQClassification:
    """Результат автоматической классификации DLQ-записи.

    Attributes:
        sensitivity: Уровень чувствительности payload'а.
        requires_redaction: True если нужна redaction перед replay.
        reason_explanation: Человеко-читаемое объяснение классификации.
        detected_patterns: Список regex-patterns которые сработали.
    """

    sensitivity: SensitivityLevel
    requires_redaction: bool
    reason_explanation: str
    detected_patterns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DLQReplayResult:
    """Результат replay операции.

    Attributes:
        replay_id: UUID реплея (audit-trail unique identifier).
        step: Какой шаг был выполнен (DRY_RUN или REPLAY).
        original_event_id: Event ID оригинальной записи (для корреляции).
        dry_run: True если dry-run mode (no actual replay).
        success: True если replay успешен.
        reason: Причина replay (operator-provided, mandatory для audit).
        operator_id: ID оператора (для audit-trail).
        correlation_id: ID для distributed tracing.
        timestamp: Unix timestamp начала операции.
        metadata: Дополнительный контекст (rate_limit_remaining, redaction_count, etc.).
    """

    replay_id: str
    step: ReplayStep
    original_event_id: str
    dry_run: bool
    success: bool
    reason: str
    operator_id: str
    correlation_id: str
    timestamp: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReplayAuditEntry:
    """Audit-trail запись для DLQ replay.

    Создаётся при каждом replay (DRY_RUN или REPLAY). Сохраняет
    original event ID, replay ID, operator и reason для compliance.
    """

    replay_id: str
    original_event_id: str
    operator_id: str
    reason: str
    correlation_id: str
    timestamp: float
    dry_run: bool
    success: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)


# ──────────────────── DLQReplayGovernor ────────────────────


# PII patterns для auto-redaction (базовый набор; расширяется per-deployment).
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    (
        "phone_ru",
        re.compile(r"\+7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b"),
    ),
    ("card_number", re.compile(r"\b(?:\d[ -]?){13,16}\d\b")),
    ("passport", re.compile(r"\b\d{4}[\s\-]\d{6}\b")),  # require separator
    ("inn", re.compile(r"\b\d{10,12}\b")),  # ИНН 10/12 digits
    ("snils", re.compile(r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b")),
)


class DLQReplayGovernor:
    """Управляемая модель DLQ replay (7 шагов + governance).

    Capabilities:
        - Capability check (callback, fail-closed)
        - Rate limiting (in-memory token bucket, sliding window)
        - Audit trail (per-replay ReplayAuditEntry)
        - PII redaction (regex-based, configurable patterns)
        - Dry-run mode (no side-effects)

    Thread-safe: rate_limit_window deque защищён через single-thread access
    (async event loop). Для multi-thread — обернуть в lock.
    """

    def __init__(
        self,
        *,
        rate_limit_per_minute: int = 10,
        capability_check: Callable[[str, str], bool] | None = None,
        audit_writer: Callable[[ReplayAuditEntry], None] | None = None,
        redactor: Callable[[Any], Any] | None = None,
        replay_executor: Callable[[Any], bool] | None = None,
    ) -> None:
        """Инициализирует governor с governance hooks.

        Args:
            rate_limit_per_minute: Max replays per minute (sliding window).
            capability_check: Callback ``(capability, operator_id) -> bool``.
                Если None — capability check пропускается (NOT для prod).
            audit_writer: Callback ``(audit_entry) -> None``. Если None —
                audit trail хранится in-memory (для тестов).
            redactor: Custom redactor ``(payload) -> redacted_payload``.
                Если None — используется встроенный regex-based.
            replay_executor: Callback ``(redacted_payload) -> bool``.
                Выполняет actual replay (broker.publish, etc.).
                Если None — replay возвращает success=True (для тестов).
        """
        self._rate_limit = rate_limit_per_minute
        self._capability_check = capability_check
        self._audit_writer = audit_writer or self._default_audit_writer
        self._redactor = redactor or self._default_redactor
        self._replay_executor = replay_executor
        # Sliding window: deque of timestamps (last 60s).
        self._rate_window: deque[float] = deque(maxlen=rate_limit_per_minute * 2)
        # Audit trail (in-memory).
        self._audit_log: list[ReplayAuditEntry] = []

    # ─────────── 1. Inspect ───────────

    def inspect(self, envelope: "DLQEnvelope") -> dict[str, Any]:
        """Step 1: read-only snapshot для UI/admin.

        Возвращает dict с основными полями envelope + summary.
        НЕ модифицирует envelope.
        """
        return {
            "dlq_id": envelope.dlq_id,
            "transport": envelope.transport,
            "trace_id": envelope.trace_id,
            "tenant_id": envelope.tenant_id,
            "route_id": envelope.route_id,
            "reason": envelope.reason.value
            if hasattr(envelope.reason, "value")
            else str(envelope.reason),
            "error_class": envelope.error_class,
            "error_message": envelope.error_message,
            "retry_count": envelope.retry_count,
            "first_failed_at": envelope.first_failed_at.isoformat(),
            "last_failed_at": envelope.last_failed_at.isoformat(),
            "dlq_class": envelope.dlq_class,
            "payload_size": (
                len(str(envelope.original_payload))
                if envelope.original_payload is not None
                else 0
            ),
            "metadata": dict(envelope.metadata),
        }

    # ─────────── 2. Classify ───────────

    def classify(self, envelope: "DLQEnvelope") -> DLQClassification:
        """Step 2: автоматическая классификация по payload + reason.

        Использует:
        - DLQReason → базовая sensitivity.
        - Regex patterns → detection PII/financial patterns.
        - dlq_class → дополнительный контекст (financial/analytics/operational).
        """
        payload_str = str(envelope.original_payload or "")
        dlq_class = envelope.dlq_class.lower()
        detected: list[str] = []

        # PII detection via regex.
        for name, pattern in _PII_PATTERNS:
            if pattern.search(payload_str):
                detected.append(name)

        # Financial detection via dlq_class.
        if dlq_class == "financial":
            detected.append("dlq_class:financial")

        # Determine sensitivity level.
        if "card_number" in detected or "passport" in detected:
            sensitivity = SensitivityLevel.FINANCIAL
            requires_redaction = True
            explanation = "Обнаружены card_number/passport → FINANCIAL"
        elif any(p in detected for p in ("inn", "snils", "phone_ru", "email")):
            sensitivity = SensitivityLevel.PII
            requires_redaction = True
            explanation = "Обнаружены PII patterns → PII (redact before replay)"
        elif dlq_class == "financial":
            sensitivity = SensitivityLevel.FINANCIAL
            requires_redaction = True
            explanation = "dlq_class=financial → FINANCIAL"
        elif envelope.reason.value == "capability_denied":
            sensitivity = SensitivityLevel.CONFIDENTIAL
            requires_redaction = False
            explanation = "capability_denied → внутренняя ошибка auth, replay безопасен"
        else:
            sensitivity = SensitivityLevel.INTERNAL
            requires_redaction = False
            explanation = "Без PII/financial markers → INTERNAL"

        return DLQClassification(
            sensitivity=sensitivity,
            requires_redaction=requires_redaction,
            reason_explanation=explanation,
            detected_patterns=tuple(detected),
        )

    # ─────────── 3. Redact ───────────

    def redact(self, envelope: "DLQEnvelope") -> Any:
        """Step 3: redact PII из payload перед replay.

        Возвращает redacted payload (или original если redaction не нужна).
        """
        classification = self.classify(envelope)
        if not classification.requires_redaction:
            return envelope.original_payload
        return self._redactor(envelope.original_payload)

    def _default_redactor(self, payload: Any) -> Any:
        """Default regex-based redactor (PII patterns).

        Handles:
        - dict/list payloads → recursive redaction (preserves structure).
        - str payloads → either JSON-parsed recursive, or flat string redaction.
        - Other types → str() + flat redaction.
        """
        if payload is None:
            return None
        if isinstance(payload, (dict, list)):
            return self._redact_recursive(payload)
        if isinstance(payload, str):
            # Try JSON parse first (for structured payloads).
            if payload.startswith("{") or payload.startswith("["):
                import json

                try:
                    return self._redact_recursive(json.loads(payload))
                except json.JSONDecodeError, ValueError:
                    pass  # fall through to flat redaction
            # Flat string redaction.
            text = payload
            for name, pattern in _PII_PATTERNS:
                text = pattern.sub(f"[REDACTED:{name}]", text)
            return text
        # Other types → str + flat redaction.
        text = str(payload)
        for name, pattern in _PII_PATTERNS:
            text = pattern.sub(f"[REDACTED:{name}]", text)
        return text

    def _redact_recursive(self, obj: Any) -> Any:
        """Recursively redact dict/list values."""
        if isinstance(obj, dict):
            return {k: self._redact_recursive(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._redact_recursive(item) for item in obj]
        if isinstance(obj, str):
            for name, pattern in _PII_PATTERNS:
                obj = pattern.sub(f"[REDACTED:{name}]", obj)
        return obj

    # ─────────── 4-5. Replay (dry-run + real) ───────────

    def replay(
        self,
        envelope: "DLQEnvelope",
        *,
        dry_run: bool,
        operator_id: str,
        reason: str,
        correlation_id: str = "",
    ) -> DLQReplayResult:
        """Step 4/5: dry-run OR actual replay с governance checks.

        Проверки (в порядке):
        1. Reason не пустой (operator обязан объяснить).
        2. Rate limit (sliding window per minute).
        3. Capability check (если настроен).
        4. Redaction (auto, на основе classify).
        5. Replay executor (или no-op для тестов).
        6. Audit trail.

        Args:
            envelope: DLQ-запись для replay.
            dry_run: True → simulate without side-effects.
            operator_id: ID оператора (для audit).
            reason: ОБЯЗАТЕЛЬНАЯ причина (для audit-trail).
            correlation_id: Distributed-tracing ID.

        Returns:
            DLQReplayResult с success=True при успехе.

        Raises:
            ValueError: Если reason пустой.
            RateLimitExceededError: Если превышен rate limit.
            CapabilityDeniedError: Если capability check failed.
        """
        # Validate operator reason.
        if not reason or not reason.strip():
            raise ValueError(
                "reason обязателен для audit-trail (operator должен объяснить зачем)"
            )

        step = ReplayStep.DRY_RUN if dry_run else ReplayStep.REPLAY
        replay_id = str(uuid4())
        original_event_id = (
            envelope.metadata.get("event_id", envelope.dlq_id)
            if envelope.metadata
            else envelope.dlq_id
        )
        now = time.time()
        metadata: dict[str, Any] = {}

        # 1. Capability check (fail-closed).
        if self._capability_check is not None and not dry_run:
            cap = "dlq.replay"
            if not self._capability_check(cap, operator_id):
                raise _CapabilityDeniedError(capability=cap, operator_id=operator_id)

        # 2. Rate limit check.
        rate_ok, remaining = self._check_rate_limit(now)
        metadata["rate_limit_remaining"] = remaining
        if not rate_ok and not dry_run:
            raise _RateLimitExceededError(
                limit=self._rate_limit, window_seconds=60, operator_id=operator_id
            )

        # 3. Redaction (always done, even in dry-run, для visibility).
        redacted = self.redact(envelope)
        if (
            envelope.original_payload is not None
            and redacted != envelope.original_payload
        ):
            metadata["redacted"] = True

        # 4. Replay execution (only if not dry_run AND executor configured).
        success = True
        if not dry_run and self._replay_executor is not None:
            try:
                success = self._replay_executor(redacted)
            except Exception as exc:  # noqa: BLE001
                success = False
                metadata["executor_error"] = str(exc)

        # 5. Audit trail.
        audit_entry = ReplayAuditEntry(
            replay_id=replay_id,
            original_event_id=original_event_id,
            operator_id=operator_id,
            reason=reason,
            correlation_id=correlation_id,
            timestamp=now,
            dry_run=dry_run,
            success=success,
            metadata=dict(metadata),
        )
        self._audit_writer(audit_entry)

        return DLQReplayResult(
            replay_id=replay_id,
            step=step,
            original_event_id=original_event_id,
            dry_run=dry_run,
            success=success,
            reason=reason,
            operator_id=operator_id,
            correlation_id=correlation_id,
            timestamp=now,
            metadata=metadata,
        )

    # ─────────── 6. Verify ───────────

    def verify(self, replay_id: str, success: bool) -> bool:
        """Step 6: verify replay успешен (по audit log).

        Returns:
            True если replay найден в audit log и success=True.
        """
        for entry in self._audit_log:
            if entry.replay_id == replay_id:
                return entry.success == success
        return False

    # ─────────── 7. Archive ───────────

    def archive(self, envelope: "DLQEnvelope") -> str:
        """Step 7: archive envelope в cold storage.

        По умолчанию: перемещает в audit log с пометкой archived.
        Production: интеграция с S3/MinIO Glacier tier.

        Returns:
            archive_id (UUID) для последующего retrieve.
        """
        archive_id = str(uuid4())
        # Default: log-only. Production integration — out of scope здесь.
        if self._audit_writer is not None:
            self._audit_writer(
                ReplayAuditEntry(
                    replay_id=archive_id,
                    original_event_id=envelope.dlq_id,
                    operator_id="system",
                    reason="archive",
                    correlation_id="",
                    timestamp=time.time(),
                    dry_run=True,
                    success=True,
                    metadata={"step": "archive", "dlq_class": envelope.dlq_class},
                )
            )
        return archive_id

    # ─────────── Audit + rate limit helpers ───────────

    def get_audit_log(self) -> list[ReplayAuditEntry]:
        """Возвращает audit log (для тестов и admin UI)."""
        return list(self._audit_log)

    def _default_audit_writer(self, entry: ReplayAuditEntry) -> None:
        """Default audit writer: in-memory list."""
        self._audit_log.append(entry)

    def _check_rate_limit(self, now: float) -> tuple[bool, int]:
        """Проверяет sliding window rate limit. Returns (allowed, remaining)."""
        # Drop timestamps older than 60s.
        cutoff = now - 60.0
        while self._rate_window and self._rate_window[0] < cutoff:
            self._rate_window.popleft()

        if len(self._rate_window) >= self._rate_limit:
            return False, 0

        self._rate_window.append(now)
        return True, self._rate_limit - len(self._rate_window)


# ──────────────────── Exceptions ────────────────────


class _CapabilityDeniedError(Exception):
    """Capability check failed (нет прав на dlq.replay)."""

    def __init__(self, *, capability: str, operator_id: str) -> None:
        self.capability = capability
        self.operator_id = operator_id
        super().__init__(
            f"Capability denied: operator={operator_id!r} "
            f"отсутствует capability={capability!r}"
        )


class _RateLimitExceededError(Exception):
    """Rate limit превышен (sliding window)."""

    def __init__(self, *, limit: int, window_seconds: int, operator_id: str) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.operator_id = operator_id
        super().__init__(
            f"Rate limit exceeded: {limit} replays per {window_seconds}s "
            f"for operator={operator_id!r}"
        )


# Публичные имена для удобства импорта (snake_case-friendly).
CapabilityDeniedError = _CapabilityDeniedError
RateLimitExceededError = _RateLimitExceededError
