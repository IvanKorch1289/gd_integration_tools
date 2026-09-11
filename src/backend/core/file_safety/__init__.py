"""File Safety: manifest + quarantine + atomic handoff (Wave 1 P0 #37-#39).

Проблема (EP-R1):
    Файлы, попадающие в систему:
    - Без manifest (что это, откуда, кто загрузил, hash).
    - Без AV/type/size policy (malware/corruption/DoS).
    - Consumer читает неполный файл (atomicity).

Решение:
    ``FileSafetyService`` объединяет 3 P0 элемента:

    1. **Manifest** (#37) — ``FileManifest`` с file_id (UUID),
       SHA-256 hash, source, tenant, classification, trace_id.

    2. **Quarantine** (#38) — ``quarantine_file()`` проверяет:
       - AV scan (если enabled).
       - MIME type whitelist.
       - Size limits.
       - PII detection (basic).
       Решает: RELEASE / QUARANTINE / REJECT.

    3. **Atomic handoff** (#39) — ``promote_to_consumer()``:
       - Stage в temp location.
       - Compute hash + manifest.
       - Atomic move (rename) → consumers see только complete file.

Использование::

    from src.backend.core.file_safety import get_file_safety_service

    svc = get_file_safety_service()

    # 1. Stage file.
    staged_path = svc.stage_file(content=b"...", filename="report.pdf")

    # 2. Quarantine + manifest.
    result = svc.quarantine_and_manifest(
        staged_path=staged_path,
        source="upload-api",
        tenant_id="tenant-1",
    )
    if result.decision == QuarantineDecision.RELEASE:
        # 3. Atomic promote to consumer location.
        final_path = svc.promote_to_consumer(
            manifest=result.manifest,
            target_dir="/var/lib/consumer/inbox",
        )
"""

from __future__ import annotations

from src.backend.core.file_safety.atomic import AtomicHandoff
from src.backend.core.file_safety.manifest import FileManifest, FileSafetyService
from src.backend.core.file_safety.quarantine import (
    QuarantineDecision,
    QuarantinePolicy,
    QuarantineResult,
    get_file_safety_service,
)

__all__ = (
    "AtomicHandoff",
    "FileManifest",
    "FileSafetyService",
    "QuarantineDecision",
    "QuarantinePolicy",
    "QuarantineResult",
    "get_file_safety_service",
)
