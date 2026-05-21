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


@router.get(
    "/capabilities/graph",
    summary="Sprint 14 K5 W5: граф плагин↔capability↔ресурс",
    description="Mermaid-ready набор узлов/рёбер на основе plugin.toml::capabilities.",
    tags=["Admin · Capabilities"],
)
async def get_capability_graph() -> dict[str, Any]:
    """Собрать узлы и рёбра для UI-визуализации.

    Узлы трёх типов:
        * ``plugin``  — имя плагина;
        * ``capability`` — capability.name;
        * ``resource``  — производный resource из имени capability
          (``db.read`` → ``db``, ``net.outbound`` → ``net``).
    """
    from pathlib import Path

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    extensions_dir = Path("extensions")
    if not extensions_dir.is_dir():
        return {"nodes": [], "edges": []}

    try:
        from src.backend.services.plugins.manifest_v11 import (
            PluginManifestError,
            load_plugin_manifest,
        )
    except ImportError:
        return {"nodes": [], "edges": []}

    for child in sorted(extensions_dir.iterdir()):
        toml_path = child / "plugin.toml"
        if not toml_path.is_file():
            continue
        try:
            manifest = load_plugin_manifest(toml_path)
        except PluginManifestError:
            continue
        plugin_node_id = f"plugin:{manifest.name}"
        nodes.setdefault(
            plugin_node_id,
            {"id": plugin_node_id, "kind": "plugin", "label": manifest.name},
        )
        for cap in manifest.capabilities:
            cap_node_id = f"cap:{cap.name}"
            nodes.setdefault(
                cap_node_id,
                {"id": cap_node_id, "kind": "capability", "label": cap.name},
            )
            resource = cap.name.split(".", 1)[0]
            res_node_id = f"res:{resource}"
            nodes.setdefault(
                res_node_id, {"id": res_node_id, "kind": "resource", "label": resource}
            )
            edges.append(
                {
                    "source": plugin_node_id,
                    "target": cap_node_id,
                    "label": cap.scope or "*",
                }
            )
            edges.append({"source": cap_node_id, "target": res_node_id, "label": ""})

    return {"nodes": list(nodes.values()), "edges": edges}
