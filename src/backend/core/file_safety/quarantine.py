"""Quarantine pipeline для files (Wave 1 P0 #38)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.backend.core.file_safety.manifest import (
    FileManifest,
    FileSafetyService,
    compute_sha256,
)

__all__ = (
    "QuarantineDecision",
    "QuarantinePolicy",
    "QuarantineResult",
    "get_file_safety_service",
)


class QuarantineDecision(str, enum.Enum):
    """Решение по quarantined file."""

    RELEASE = "release"
    QUARANTINE = "quarantine"  # needs operator review
    REJECT = "reject"  # never reach consumers


@dataclass(slots=True)
class QuarantinePolicy:
    """Политика quarantine для file uploads."""

    max_size_bytes: int = 100 * 1024 * 1024  # 100 MB default
    allowed_mime_types: tuple[str, ...] = (
        "application/pdf",
        "image/png",
        "image/jpeg",
        "text/csv",
        "application/json",
        "text/plain",
    )
    require_av_scan: bool = False  # opt-in (ClamAV etc.)
    pii_detection_enabled: bool = False
    reject_on_size_exceeded: bool = True
    reject_on_mime_mismatch: bool = True


@dataclass(slots=True)
class QuarantineResult:
    """Результат quarantine check + manifest."""

    decision: QuarantineDecision
    manifest: FileManifest | None = None
    reasons: list[str] = field(default_factory=list)
    policy: QuarantinePolicy | None = None


class _Service:
    """Internal alias — ``get_file_safety_service()`` returns singleton."""

    pass


_service: FileSafetyService | None = None


def get_file_safety_service() -> FileSafetyService:
    """Module-level singleton accessor."""
    global _service
    if _service is None:
        _service = FileSafetyService()
    return _service


def _set_file_safety_service(svc: FileSafetyService | None) -> None:
    """Override singleton (DI)."""
    global _service
    _service = svc


def reset_file_safety_service() -> None:
    global _service
    _service = None
