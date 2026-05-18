"""К5 (Wave K5/docs-tenants-caps) — admin REST API для capabilities.

Endpoints (под ``/api/v1/admin``):

* ``GET /capabilities`` — каталог capabilities (CapabilityVocabulary +
  DEFAULT_CAPABILITY_CATALOG).
* ``GET /capabilities/audit-events`` — последние N denied
  capability-checks из audit log (для дашбордов и Streamlit page 71).

Авторизация: глобальный :class:`APIKeyMiddleware`. Capability-gate:
``admin.read.capabilities``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

__all__ = ("router",)

logger = logging.getLogger("entrypoints.admin_capabilities")

router = APIRouter()


@router.get(
    "/capabilities",
    summary="Каталог capabilities",
    description="Возвращает CapabilityVocabulary + DEFAULT_CAPABILITY_CATALOG.",
    tags=["Admin · Capabilities"],
)
async def list_capabilities() -> dict[str, Any]:
    """Список всех известных capabilities."""
    try:
        from src.backend.core.security.capabilities import (
            DEFAULT_CAPABILITY_CATALOG,
            build_default_vocabulary,
        )
    except ImportError as exc:
        logger.warning("capabilities module unavailable: %s", exc)
        return {"vocabulary": [], "catalog": [], "stub": True}

    vocab = build_default_vocabulary()
    items = []
    for cap in vocab.all():
        items.append(
            {
                "name": cap.name,
                "description": cap.description,
                "scope_required": cap.scope_required,
                "public": cap.public,
                "aliases": list(cap.aliases),
            }
        )
    catalog = [{"name": str(c)} for c in (DEFAULT_CAPABILITY_CATALOG or [])]
    return {"vocabulary": items, "catalog": catalog, "stub": False}


@router.get(
    "/capabilities/audit-events",
    summary="Recent capability-denied events",
    description="Последние N audit-events с event_type='capability_denied'.",
    tags=["Admin · Capabilities"],
)
async def get_capability_audit_events(limit: int = 100) -> dict[str, Any]:
    """Последние denied capability-checks.

    В отсутствие живого ClickHouse audit log возвращает пустой список —
    Streamlit page 71 toleratет stub-режим.
    """
    safe_limit = max(1, min(int(limit), 1000))
    try:
        from src.backend.infrastructure.audit.event_log import get_audit_log
    except ImportError:
        return {"events": [], "limit": safe_limit, "stub": True}

    log = get_audit_log()
    try:
        rows = await log.query(entity_type="capability", limit=safe_limit)
    except Exception as exc:  # pragma: no cover — ClickHouse offline
        logger.warning("audit-log query failed: %s", exc)
        rows = []

    return {"events": rows, "limit": safe_limit, "stub": not rows}
