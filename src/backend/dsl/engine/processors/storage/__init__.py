"""Storage DSL-процессоры (S61 W3).

Использует :func:`src.backend.infrastructure.storage.factory.get_object_storage`
для получения :class:`ObjectStorage` backend (S3/MinIO/LocalFS).

Процессоры:
* :class:`ToS3Processor` — загрузить байты в storage.
* :class:`FromS3Processor` — скачать байты из storage.
* :class:`S3PresignProcessor` — получить presigned URL.
* :class:`S3DeleteProcessor` — удалить объект.
* :class:`S3ListProcessor` — список ключей с префиксом.

Безопасность: key validation (path-traversal, absolute, empty) —
через :meth:`S3ObjectStorage._safe_key` (mirror LocalFSStorage).
"""

from src.backend.dsl.engine.processors.storage.s3 import (
    FromS3Processor,
    S3DeleteProcessor,
    S3ListProcessor,
    S3PresignProcessor,
    ToS3Processor,
)

__all__ = (
    "FromS3Processor",
    "S3DeleteProcessor",
    "S3ListProcessor",
    "S3PresignProcessor",
    "ToS3Processor",
)
