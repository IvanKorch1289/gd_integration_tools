"""Worker Versioning helper (S171 M10 P0).

Per https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning:
Temporal Worker Versioning — mechanism для безопасного rollout workflow-кода.
BuildID-based pinning: каждый Execution привязан к worker version где стартовал.

Преимущества:
- Безопасный deploy: новый worker не выполняет старые executions
- Cleaner rollback: pinned workflows continue on original version
- Без deprecated ``workflow.patched()`` (legacy API)

Pattern (Ponytail, D172): тонкая обёртка над temporalio SDK.
Lazy imports: temporalio SDK ~15-20MB, не подтягиваем до первого использования.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("workflow.worker_versioning")

__all__ = (
    "VersioningPolicy",
    "WorkerVersioningHelper",
    "parse_build_id",
)


_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[\w.]+)?$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def parse_build_id(raw: str) -> tuple[str, str]:
    """Парсить Build ID, определить его тип (semver/git/custom).

    Args:
        raw: Build ID (semver, git SHA, или custom string).

    Returns:
        Кортеж (kind, normalized_value).
    """
    raw = raw.strip()
    if _SEMVER_RE.match(raw):
        return ("semver", raw)
    if _GIT_SHA_RE.match(raw):
        # Нормализуем: для совместимости с Temporal (требует hex)
        return ("git", raw[:40])
    return ("custom", raw)


@dataclass
class VersioningPolicy:
    """Стратегия rollout для новой версии.

    Attributes:
        deployment_name: Имя deployment (например, "gd-integration-tools").
        build_id: Build ID новой версии (semver/git/custom).
        ramp_percentage: Процент трафика на новой версии (0-100).
        auto_upgrade: Автоматически upgrade pinned workflows (если True).
    """

    deployment_name: str
    build_id: str
    ramp_percentage: int = 100
    auto_upgrade: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.ramp_percentage <= 100:
            raise ValueError(
                f"VersioningPolicy: ramp_percentage должен быть 0-100, "
                f"получено {self.ramp_percentage}"
            )


class WorkerVersioningHelper:
    """Helper для создания Temporal Worker с Worker Versioning.

    Args:
        deployment_name: Имя deployment (одинаковое для всех версий).
        build_id: Build ID этой версии worker.
        use_versioning: Включить Worker Versioning (default: False).
        policy: Стратегия rollout (default: 100% на этой версии).
    """

    def __init__(
        self,
        *,
        deployment_name: str,
        build_id: str,
        use_versioning: bool = False,
        policy: VersioningPolicy | None = None,
    ) -> None:
        if not deployment_name:
            raise ValueError("deployment_name обязательно")
        if not build_id:
            raise ValueError("build_id обязательно")
        self.deployment_name = deployment_name
        self.build_id = build_id
        self.use_versioning = use_versioning
        self.policy = policy or VersioningPolicy(
            deployment_name=deployment_name, build_id=build_id
        )

    def build_worker_kwargs(self) -> dict[str, Any]:
        """Собрать kwargs для передачи в ``temporalio.worker.Worker()``.

        Returns:
            Dict с ключами ``build_id`` и опционально ``deployment_options``.
        """
        kwargs: dict[str, Any] = {"build_id": self.build_id}
        if self.use_versioning:
            # Lazy import — temporalio SDK ~15-20MB
            try:
                from temporalio.worker import (
                    DeploymentConfig,
                    VersioningIntent,
                    WorkerDeploymentOptions,
                )
            except ImportError:
                _logger.warning(
                    "worker_versioning.temporalio.unavailable",
                    extra={"hint": "pip install temporalio для Worker Versioning"},
                )
                return kwargs

            kwargs["deployment_options"] = WorkerDeploymentOptions(
                version=DeploymentConfig(
                    deployment_name=self.deployment_name,
                    build_id=self.build_id,
                ),
                use_worker_versioning=True,
            )
            _logger.info(
                "worker_versioning.enabled deployment=%s build_id=%s ramp=%d%%",
                self.deployment_name,
                self.build_id,
                self.policy.ramp_percentage,
            )
        return kwargs

    def should_route_to_this_version(self, ramp_seed: int = 0) -> bool:
        """Решить, должен ли новый Execution идти на эту версию (ramping).

        Args:
            ramp_seed: Детерминированный seed (например, workflow_id hash).

        Returns:
            True если Execution должен идти на эту версию.
        """
        if self.policy.ramp_percentage >= 100:
            return True
        if self.policy.ramp_percentage <= 0:
            return False
        # Простая детерминированная рандомизация по seed
        return (ramp_seed % 100) < self.policy.ramp_percentage
