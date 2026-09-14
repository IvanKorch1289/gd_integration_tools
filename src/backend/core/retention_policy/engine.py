"""Retention Policy Engine — pure-Python (Wave 4 #74)."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "LegalHold",
    "RetentionAction",
    "RetentionEngine",
    "RetentionPolicy",
    "RetentionVerdict",
    "get_retention_engine",
)


class RetentionAction(str, enum.Enum):
    """Action to take когда retention policy applies."""

    KEEP = "keep"  # Continue storing.
    ARCHIVE = "archive"  # Move to cold storage.
    ANONYMIZE = "anonymize"  # Strip PII, keep aggregates.
    DELETE = "delete"  # Hard delete.


@dataclass(slots=True)
class RetentionPolicy:
    """Single retention policy.

    Attributes:
        data_type: Type identifier (e.g., "audit_log", "session_token").
        retention_days: How long to keep (days from creation).
        action: What to do after retention period.
        anonymize_fields: Fields to strip on anonymize (e.g., ["email", "phone"]).
    """

    data_type: str
    retention_days: int
    action: RetentionAction = RetentionAction.DELETE
    anonymize_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class LegalHold:
    """Legal hold flag — blocks delete even after retention expiry."""

    data_type: str
    reason: str
    created_at: str  # ISO timestamp.
    expires_at: str | None = None  # ISO timestamp, None = permanent.


@dataclass(slots=True)
class RetentionVerdict:
    """Result of policy evaluation."""

    data_type: str
    age_days: float
    action: RetentionAction
    reason: str = ""
    blocked_by_hold: bool = False


class RetentionEngine:
    """Registry + evaluator для retention policies."""

    def __init__(self) -> None:
        self._policies: dict[str, RetentionPolicy] = {}
        self._holds: list[LegalHold] = []

    # ─── Policy registration ──────────────────────────

    def register(self, policy: RetentionPolicy) -> None:
        self._policies[policy.data_type] = policy

    def get(self, data_type: str) -> RetentionPolicy | None:
        return self._policies.get(data_type)

    def list_policies(self) -> list[RetentionPolicy]:
        return list(self._policies.values())

    def policy_count(self) -> int:
        return len(self._policies)

    # ─── Legal hold management ─────────────────────────

    def add_hold(self, hold: LegalHold) -> None:
        self._holds.append(hold)

    def remove_hold(
        self, data_type: str, reason: str
    ) -> int:
        """Remove holds by data_type + reason. Returns count."""
        before = len(self._holds)
        self._holds = [
            h
            for h in self._holds
            if not (h.data_type == data_type and h.reason == reason)
        ]
        return before - len(self._holds)

    def list_holds(self) -> list[LegalHold]:
        return list(self._holds)

    def holds_for_type(self, data_type: str) -> list[LegalHold]:
        return [h for h in self._holds if h.data_type == data_type]

    def has_active_hold(
        self, data_type: str, now: datetime | None = None
    ) -> bool:
        """Check if data_type has active hold."""
        current = now or datetime.now(UTC)
        for hold in self._holds:
            if hold.data_type != data_type:
                continue
            if hold.expires_at is None:
                return True
            expires = datetime.fromisoformat(hold.expires_at)
            if current < expires:
                return True
        return False

    # ─── Evaluation ──────────────────────────────────

    def evaluate(
        self,
        data_type: str,
        age_days: float,
    ) -> RetentionVerdict:
        """Evaluate retention policy для data_type с заданным возрастом.

        Returns:
            :class:`RetentionVerdict` с action + blocked_by_hold flag.
        """
        policy = self._policies.get(data_type)
        if policy is None:
            # No policy → keep by default (defensive).
            return RetentionVerdict(
                data_type=data_type,
                age_days=age_days,
                action=RetentionAction.KEEP,
                reason="no policy defined",
            )

        # Within retention period → keep.
        if age_days <= policy.retention_days:
            return RetentionVerdict(
                data_type=data_type,
                age_days=age_days,
                action=RetentionAction.KEEP,
                reason=f"within retention window ({policy.retention_days}d)",
            )

        # Past retention → check legal hold.
        if self.has_active_hold(data_type):
            return RetentionVerdict(
                data_type=data_type,
                age_days=age_days,
                action=RetentionAction.KEEP,
                reason="legal hold blocks deletion",
                blocked_by_hold=True,
            )

        # Apply policy action.
        return RetentionVerdict(
            data_type=data_type,
            age_days=age_days,
            action=policy.action,
            reason=f"past retention ({policy.retention_days}d)",
        )

    def apply_to_record(
        self,
        record: dict[str, Any],
        data_type: str,
        created_at: datetime,
        now: datetime | None = None,
    ) -> RetentionVerdict:
        """Evaluate policy для record + apply action (mutates record)."""
        current = now or datetime.now(UTC)
        age = (current - created_at).total_seconds() / 86400.0
        verdict = self.evaluate(data_type, age)

        if verdict.action == RetentionAction.DELETE:
            # Caller should drop the record (we return verdict, not mutate).
            pass
        elif verdict.action == RetentionAction.ANONYMIZE:
            for field in self.get(data_type).anonymize_fields:
                if field in record:
                    record[field] = "[REDACTED]"
        elif verdict.action == RetentionAction.ARCHIVE:
            record["_archived_at"] = current.isoformat()

        return verdict

    def clear(self) -> None:
        self._policies.clear()
        self._holds.clear()


_engine: RetentionEngine | None = None


def get_retention_engine() -> RetentionEngine:
    global _engine
    if _engine is None:
        _engine = RetentionEngine()
    return _engine


def reset_retention_engine() -> None:
    global _engine
    _engine = None


# Helper for tests.
def _days_ago(n: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=n)
