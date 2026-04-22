"""CloudEvents 1.0 envelope (ADR-010).

Все события в Kafka / RabbitMQ / FastStream упаковываются в CE-envelope.
Поля обязательны: id, source, specversion='1.0', type, time,
datacontenttype, subject, data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = ("CloudEvent", "envelope", "parse_envelope")


@dataclass(slots=True)
class CloudEvent:
    """CloudEvents 1.0 envelope — минимальный набор полей."""

    type: str
    source: str
    subject: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    specversion: str = "1.0"
    datacontenttype: str = "application/json"
    data: Any = None
    dataschema: str | None = None  # URL schema в Schema Registry (C4)
    tenantid: str | None = None  # extension для multi-tenant (G1)
    traceparent: str | None = None  # OTEL propagation

    def to_dict(self) -> dict[str, Any]:
        out = {
            "specversion": self.specversion,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time,
            "datacontenttype": self.datacontenttype,
        }
        if self.subject is not None:
            out["subject"] = self.subject
        if self.dataschema is not None:
            out["dataschema"] = self.dataschema
        if self.tenantid is not None:
            out["tenantid"] = self.tenantid
        if self.traceparent is not None:
            out["traceparent"] = self.traceparent
        if self.data is not None:
            out["data"] = self.data
        return out


def envelope(
    *,
    event_type: str,
    source: str,
    data: Any,
    subject: str | None = None,
    dataschema: str | None = None,
    tenantid: str | None = None,
    traceparent: str | None = None,
) -> dict[str, Any]:
    """Строит готовый CE-envelope как dict (для публикации в broker)."""
    return CloudEvent(
        type=event_type,
        source=source,
        subject=subject,
        data=data,
        dataschema=dataschema,
        tenantid=tenantid,
        traceparent=traceparent,
    ).to_dict()


def parse_envelope(raw: dict[str, Any]) -> CloudEvent:
    """Парсит incoming CE-envelope в структуру CloudEvent."""
    return CloudEvent(
        type=raw.get("type", ""),
        source=raw.get("source", ""),
        subject=raw.get("subject"),
        id=raw.get("id") or str(uuid.uuid4()),
        time=raw.get("time") or datetime.now(timezone.utc).isoformat(),
        specversion=raw.get("specversion", "1.0"),
        datacontenttype=raw.get("datacontenttype", "application/json"),
        data=raw.get("data"),
        dataschema=raw.get("dataschema"),
        tenantid=raw.get("tenantid"),
        traceparent=raw.get("traceparent"),
    )
