"""TDD: Worker Versioning helper (S171 M10 P0).

Per https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning:
- Worker(build_id=..., deployment_options=WorkerDeploymentOptions(...))
- use_worker_versioning=True для ramp/sunset routing

Pattern (Ponytail, D172): тонкая обёртка над temporalio SDK.
"""
# ruff: noqa: S101
from __future__ import annotations
from unittest.mock import MagicMock

import pytest


class TestWorkerVersioningHelper:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.workflow.versioning.worker_versioning import (
            WorkerVersioningHelper,
        )
        helper = WorkerVersioningHelper(
            deployment_name="gd-integration-tools",
            build_id="1.0.0",
        )
        assert helper.deployment_name == "gd-integration-tools"
        assert helper.build_id == "1.0.0"

    def test_default_versioning_disabled(self) -> None:
        """По умолчанию Worker Versioning отключён (backward-compat)."""
        from src.backend.infrastructure.workflow.versioning.worker_versioning import (
            WorkerVersioningHelper,
        )
        helper = WorkerVersioningHelper(
            deployment_name="gd", build_id="1.0.0"
        )
        assert helper.use_versioning is False

    def test_enable_versioning(self) -> None:
        from src.backend.infrastructure.workflow.versioning.worker_versioning import (
            WorkerVersioningHelper,
        )
        helper = WorkerVersioningHelper(
            deployment_name="gd",
            build_id="1.0.0",
            use_versioning=True,
        )
        assert helper.use_versioning is True

    def test_build_worker_kwargs_returns_dict(self) -> None:
        """build_worker_kwargs() возвращает dict для передачи в Worker()."""
        from src.backend.infrastructure.workflow.versioning.worker_versioning import (
            WorkerVersioningHelper,
        )
        helper = WorkerVersioningHelper(
            deployment_name="gd-prod", build_id="v1.0.0", use_versioning=True
        )
        kwargs = helper.build_worker_kwargs()
        assert "deployment_options" in kwargs or "build_id" in kwargs

    def test_parse_build_id_from_git_sha(self) -> None:
        """Build ID может быть git SHA или semantic version."""
        from src.backend.infrastructure.workflow.versioning.worker_versioning import (
            WorkerVersioningHelper,
            parse_build_id,
        )
        # Semver
        assert parse_build_id("1.2.3") == ("semver", "1.2.3")
        # Git SHA (7-40 hex)
        assert parse_build_id("abc1234") == ("git", "abc1234")  # truncated/normalized
        # Custom
        result = parse_build_id("release-2024-01")
        assert result[0] == "custom"


class TestVersioningPolicy:
    """Стратегии rollout (auto/ramped/legacy)."""

    def test_instantiates(self) -> None:
        from src.backend.infrastructure.workflow.versioning.worker_versioning import (
            VersioningPolicy,
        )
        policy = VersioningPolicy(
            deployment_name="gd",
            build_id="1.0.0",
        )
        assert policy.deployment_name == "gd"

    def test_ramp_percentage(self) -> None:
        from src.backend.infrastructure.workflow.versioning.worker_versioning import (
            VersioningPolicy,
        )
        policy = VersioningPolicy(
            deployment_name="gd", build_id="1.0.0", ramp_percentage=25
        )
        assert policy.ramp_percentage == 25

    def test_default_ramp_100(self) -> None:
        from src.backend.infrastructure.workflow.versioning.worker_versioning import (
            VersioningPolicy,
        )
        policy = VersioningPolicy(deployment_name="gd", build_id="1.0.0")
        assert policy.ramp_percentage == 100  # default: 100% на этой версии
