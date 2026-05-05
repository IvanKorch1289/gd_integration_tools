"""SQLAlchemy-модель таблицы ``dsl_snapshots`` (Wave 1.4).

Снэпшоты определений DSL-маршрутов с версионированием. Перенесено из
Redis (см. ``.claude/REDIS_AUDIT.md``): требуется история, A/B и rollback —
кэш-хранилище неприемлемо.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.migrations._compat import json_b
from src.infrastructure.database.models.base import BaseModel

__all__ = ("DslSnapshot",)


class DslSnapshot(BaseModel):
    """Версионированный снэпшот pipeline маршрута."""

    __tablename__ = "dsl_snapshots"
    __versioned__ = {"versioning": False}
    __table_args__ = (
        UniqueConstraint("route_id", "version", name="uq_dsl_snapshots_route_ver"),
        Index("idx_dsl_snapshots_route", "route_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(json_b(), nullable=False)

    feature_flag: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    api_version: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="v2"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
