"""Atomic handoff — temp file → atomic rename (Wave 1 P0 #39)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from src.backend.core.file_safety.manifest import FileManifest

__all__ = ("AtomicHandoff",)


class AtomicHandoff:
    """Atomic file promotion from staging → consumer location.

    Использует ``os.rename()`` (atomic на same filesystem).
    Гарантирует, что consumer видит только complete file (через manifest + checksum).
    """

    @staticmethod
    def promote(
        *,
        staged_path: Path | str,
        target_dir: Path | str,
        target_filename: str | None = None,
    ) -> Path:
        """Promote staged file → target_dir atomic.

        Args:
            staged_path: Path to staged file.
            target_dir: Consumer-visible directory.
            target_filename: Target filename (default = staged filename).

        Returns:
            Final path в target_dir.

        """
        staged = Path(staged_path)
        if not staged.exists():
            raise FileNotFoundError(f"Staged file not found: {staged}")
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        final_filename = target_filename or staged.name
        final_path = target / final_filename
        # Atomic rename.
        os.rename(staged, final_path)
        return final_path

    @staticmethod
    def verify_checksum(
        *,
        path: Path | str,
        expected_sha256: str,
    ) -> bool:
        """Verify file integrity via SHA-256."""
        import hashlib
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return actual == expected_sha256
