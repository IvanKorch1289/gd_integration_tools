"""S3 client pool package (S56 W3 decomp from s3_pool.py 591 LOC).

2 classes decomposed в 2 files:
- ``base.py``: BaseS3Client (15 methods, abstract)
- ``client.py``: S3Client (20 methods, concrete impl)

Backward-compat: ``from src.backend.infrastructure.clients.storage.s3_pool import S3Client`` works.
"""

from __future__ import annotations

from src.backend.infrastructure.clients.storage.s3_pool.base import (
    BaseS3Client,  # S56 W3: re-export
)
from src.backend.infrastructure.clients.storage.s3_pool.client import (
    S3Client,  # S56 W3: re-export
)

__all__ = ("BaseS3Client", "S3Client", "get_s3_client")


def get_s3_client() -> S3Client:
    """Lazy singleton ``S3Client`` (Wave 6.1).

    aiobotocore — опциональная зависимость; ``S3Client.__init__`` лениво
    обходит её отсутствие. Откладываем инициализацию до первого
    обращения, чтобы не падать на import в dev_light окружении.
    """
    return S3Client(settings=settings.storage)


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``s3_client``."""
    if name == "s3_client":
        return get_s3_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
