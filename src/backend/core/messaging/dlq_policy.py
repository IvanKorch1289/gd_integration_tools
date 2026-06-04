"""DLQ retention policies per message-type (S13 K3 W4).

Классификация:

* ``financial`` — 7 лет (2555 дней), unlimited replays (по решению operator);
* ``analytics`` — 30 дней, 3 replays max;
* ``operational`` — 90 дней, 10 replays max (default).

Routing по ``dlq_class`` в :class:`DLQEnvelope`:

1. Explicit в ``route.toml::[dlq] dlq_class = "financial"``;
2. ``dispatch_action`` mapping (``category=financial`` → ``"financial"``);
3. Default — ``"operational"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("DLQPolicy", "DLQPolicyRegistry", "default_policy_registry")


@dataclass(frozen=True, slots=True)
class DLQPolicy:
    """Retention-конфиг для одного класса DLQ-сообщений.

    Attributes:
        class_name: Имя класса (``financial`` / ``analytics`` / ``operational``).
        retention_days: Сколько дней хранить до cleanup'а.
        max_replays: Максимальное число replays (-1 = unlimited).
        auto_archive_after_days: Перевод в cold storage через N дней.
    """

    class_name: str
    retention_days: int
    max_replays: int
    auto_archive_after_days: int


class DLQPolicyRegistry:
    """Каталог policy по ``class_name``."""

    def __init__(self) -> None:
        self._policies: dict[str, DLQPolicy] = {}

    def register(self, policy: DLQPolicy) -> None:
        self._policies[policy.class_name] = policy

    def get(self, class_name: str) -> DLQPolicy | None:
        return self._policies.get(class_name)

    def get_or_default(self, class_name: str) -> DLQPolicy:
        """Возвращает policy или fallback на ``operational``."""
        policy = self._policies.get(class_name)
        if policy is not None:
            return policy
        return self._policies.get("operational") or DLQPolicy(
            class_name="operational",
            retention_days=90,
            max_replays=10,
            auto_archive_after_days=30,
        )

    def list_all(self) -> list[DLQPolicy]:
        return list(self._policies.values())

    def resolve_for_envelope(self, envelope: DLQEnvelope) -> DLQPolicy:
        """Возвращает policy на основе ``envelope.dlq_class``."""
        return self.get_or_default(envelope.dlq_class)


def _build_default_registry() -> DLQPolicyRegistry:
    """Регистрирует 3 default policies (S13 K3 W4)."""
    registry = DLQPolicyRegistry()
    registry.register(
        DLQPolicy(
            class_name="financial",
            retention_days=2555,  # 7 лет (compliance/legal)
            max_replays=-1,  # unlimited — операторский discretion
            auto_archive_after_days=365,
        )
    )
    registry.register(
        DLQPolicy(
            class_name="analytics",
            retention_days=30,
            max_replays=3,
            auto_archive_after_days=7,
        )
    )
    registry.register(
        DLQPolicy(
            class_name="operational",
            retention_days=90,
            max_replays=10,
            auto_archive_after_days=30,
        )
    )
    return registry


default_policy_registry = _build_default_registry()
