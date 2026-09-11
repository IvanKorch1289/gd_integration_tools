"""FileManifest + FileSafetyService (Wave 1 P0 #37)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ("FileManifest", "FileSafetyService")


@dataclass(slots=True)
class FileManifest:
    """Immutable manifest для tracked file.

    Attributes:
        file_id: UUID.
        hash_sha256: SHA-256 hex digest.
        size_bytes: Размер в bytes.
        filename: Original filename.
        source: Source identifier (upload-api, cdc, mq, ...).
        tenant_id: Tenant ID (multi-tenancy).
        classification: PII level ("public", "internal", "confidential", "pii").
        trace_id: OTel trace ID.
        created_at: ISO timestamp.
        attributes: Custom metadata.

    """

    file_id: str
    hash_sha256: str
    size_bytes: int
    filename: str = ""
    source: str = ""
    tenant_id: str = ""
    classification: str = "internal"
    trace_id: str = ""
    created_at: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "hash_sha256": self.hash_sha256,
            "size_bytes": self.size_bytes,
            "filename": self.filename,
            "source": self.source,
            "tenant_id": self.tenant_id,
            "classification": self.classification,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "attributes": dict(self.attributes),
        }


def compute_sha256(content: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(content).hexdigest()


class FileSafetyService:
    """Service для manifest creation + quarantine + atomic handoff."""

    def __init__(self, *, staging_dir: str | None = None) -> None:
        self._staging_dir = Path(staging_dir) if staging_dir else Path("/tmp/gd_filesafety_staging")
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    @property
    def staging_dir(self) -> Path:
        return self._staging_dir

    def create_manifest(
        self,
        *,
        content: bytes,
        filename: str = "",
        source: str = "",
        tenant_id: str = "",
        classification: str = "internal",
        trace_id: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> FileManifest:
        """Compute manifest из content (без staging)."""
        return FileManifest(
            file_id=str(uuid.uuid4()),
            hash_sha256=compute_sha256(content),
            size_bytes=len(content),
            filename=filename,
            source=source,
            tenant_id=tenant_id,
            classification=classification,
            trace_id=trace_id,
            created_at=datetime.now(UTC).isoformat(),
            attributes=attributes or {},
        )

    def stage_file(
        self,
        *,
        content: bytes,
        filename: str = "",
    ) -> Path:
        """Stage file в staging dir. Returns path."""
        staged = self._staging_dir / f"{uuid.uuid4()}_{filename}"
        staged.write_bytes(content)
        return staged
