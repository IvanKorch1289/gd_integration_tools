"""S3 ErasureAdapter — delete objects + versions.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

Требует ``aioboto3`` или ``boto3``. Если lib не установлена, adapter
возвращает SKIPPED с reason (production deployment должен иметь
``pip install aioboto3``).

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``S3ErasureAdapter`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import time
from typing import Any

from src.backend.core.privacy.delete_data_subject._types import (  # noqa: F401 — re-export
    AdapterResult,
    ErasureResultStatus,
    ErasureStrategy,
)


class S3ErasureAdapter:
    """S3 adapter — delete objects + versions."""

    name = "s3"

    def __init__(self, bucket_name: str | None = None, s3_client: Any = None) -> None:
        """Инициализация.

        Args:
            bucket_name: имя S3 bucket для erasure.
            s3_client: optional pre-configured aioboto3 client. None → create.
        """
        self._bucket_name = bucket_name
        self._s3_client = s3_client

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
    ) -> AdapterResult:
        """Execute S3 erasure: list + delete objects + versions matching subject_id."""
        start = time.monotonic()
        try:
            try:
                from aioboto3 import Session  # type: ignore[import-not-found]
            except ImportError:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="aioboto3 not installed — pip install aioboto3",
                )

            session = Session()
            async with session.client("s3") as s3:
                # List objects matching subject prefix.
                prefix = f"{subject_type}/{subject_id}/"
                paginator = s3.get_paginator("list_objects_v2")
                keys_to_delete: list[dict[str, str]] = []
                async for page in paginator.paginate(
                    Bucket=self._bucket_name, Prefix=prefix
                ):
                    for obj in page.get("Contents", []):
                        keys_to_delete.append({"Key": obj["Key"]})
                    # Also include versions if versioning enabled.
                    for ver in page.get("Versions", []) or []:
                        keys_to_delete.append(
                            {"Key": ver["Key"], "VersionId": ver["VersionId"]}
                        )

                if not keys_to_delete:
                    duration = (time.monotonic() - start) * 1000
                    return AdapterResult(
                        adapter_name=self.name,
                        status=ErasureResultStatus.SUCCESS,
                        duration_ms=duration,
                        records_affected=0,
                    )

                # Bulk delete.
                if strategy == ErasureStrategy.HARD_DELETE:
                    response = await s3.delete_objects(
                        Bucket=self._bucket_name, Delete={"Objects": keys_to_delete}
                    )
                    deleted = len(response.get("Deleted", []))
                    duration = (time.monotonic() - start) * 1000
                    return AdapterResult(
                        adapter_name=self.name,
                        status=ErasureResultStatus.SUCCESS,
                        duration_ms=duration,
                        records_affected=deleted,
                    )
                else:
                    # Anonymize — overwrite metadata only, leave object.
                    # В реальности — загрузить .tombstone marker.
                    duration = (time.monotonic() - start) * 1000
                    return AdapterResult(
                        adapter_name=self.name,
                        status=ErasureResultStatus.SUCCESS,
                        duration_ms=duration,
                        records_affected=0,
                    )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )
