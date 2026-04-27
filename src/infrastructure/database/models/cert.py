"""SQLAlchemy-модели TLS-сертификатов (Wave 2.1).

* :class:`CertRecord` — актуальное состояние сертификата по ``service_id``.
* :class:`CertHistory` — append-only лог замен с привязкой к ``uploaded_by``.

Связано с миграцией ``f6a7b8c9d0e1_certs``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.models.base import BaseModel

__all__ = ("CertRecord", "CertHistory")


class CertRecord(BaseModel):
    """Текущая версия сертификата для ``service_id``."""

    __tablename__ = "certs"
    __versioned__ = {"exclude": True}  # type: ignore[assignment]
    __table_args__ = (Index("idx_certs_expires", "expires_at"),)

    service_id: Mapped[str] = mapped_column(Text, primary_key=True)
    pem: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CertHistory(BaseModel):
    """Лог замен сертификата (append-only)."""

    __tablename__ = "cert_history"
    __versioned__ = {"exclude": True}  # type: ignore[assignment]
    __table_args__ = (Index("idx_cert_history_service", "service_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    service_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    pem: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    uploaded_by: Mapped[str | None] = mapped_column(Text, nullable=True)
