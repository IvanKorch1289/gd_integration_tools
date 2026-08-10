"""Temporal Worker Versioning (S171 M10 P0, BuildID-based pinning).

Per https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning
each Workflow Execution is pinned to the worker BuildID where it started —
new workers do not execute legacy executions, enabling safe rollouts and
clean rollbacks without the deprecated ``workflow.patched()`` API.

Ponytail (D172): thin wrapper over the ``temporalio`` SDK with lazy
imports (the SDK is ~15-20 MB and not loaded until first use).
"""
from __future__ import annotations as annotations

from src.backend.infrastructure.workflow.versioning.worker_versioning import (
    VersioningPolicy,
    WorkerVersioningHelper,
    parse_build_id,
)

__all__ = (
    "VersioningPolicy",
    "WorkerVersioningHelper",
    "parse_build_id",
)
