"""Бэкенды :class:`core.interfaces.watermark_store.WatermarkStore` (W14.5).

PG-реализация импортируется лениво (через ``__getattr__``), чтобы
``MemoryWatermarkStore`` оставался пригодным в окружениях без
psycopg/SQLAlchemy-стека (dev_light/unit-тесты).
"""

from __future__ import annotations as annotations

from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any

from src.backend.infrastructure.watermark.factory import create_watermark_store  # noqa: F401 — re-export
from src.backend.infrastructure.watermark.memory_store import MemoryWatermarkStore  # noqa: F401 — re-export

if TYPE_CHECKING:
    from src.backend.infrastructure.watermark.postgres_store import (
        PostgresWatermarkStore,
    )

__all__ = ("MemoryWatermarkStore", "PostgresWatermarkStore", "create_watermark_store")


def __getattr__(name: str) -> Any:
    if name == "PostgresWatermarkStore":
        from src.backend.infrastructure.watermark.postgres_store import (
            PostgresWatermarkStore as _PG,
        )

        return _PG
    raise AttributeError(name)
