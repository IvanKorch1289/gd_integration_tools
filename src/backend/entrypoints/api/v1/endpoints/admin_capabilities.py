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

from typing import Any

from fastapi import APIRouter, Depends

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.core.logging import get_logger

__all__ = ("router",)

logger = get_logger("entrypoints.admin_capabilities")

# S202 audit fix: require admin role
_ADMIN_GUARD_READ = Depends(
    require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY, AdminRole.SUPER_ADMIN))
)

router = APIRouter(dependencies=[_ADMIN_GUARD_READ])


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

    D-AUDIT-9801 fix (cycle 98, API-P1-008): на ImportError логируется
    WARNING (раньше silent return с stub=True). На query failure —
    ERROR (раньше WARNING без structured context). Caller получает
    stub=True (Streamlit page 71 tolerates), но ops увидит degradation
    в observability.
    """
    safe_limit = max(1, min(int(limit), 1000))
    try:
        from src.backend.core.audit import get_audit_log
    except ImportError as exc:
        logger.warning(
            "get_audit_log import failed (audit module unavailable): "
            "exc_type=%s exc_msg=%s — returning stub=True",
            type(exc).__name__,
            exc,
        )
        return {"events": [], "limit": safe_limit, "stub": True}

    log = get_audit_log()
    try:
        rows = await log.query(entity_type="capability", limit=safe_limit)
    except Exception as exc:  # pragma: no cover — ClickHouse offline
        # D-AUDIT-9801: structured ERROR-лог с exc_type/exc_msg.
        # Раньше: bare warning → signal терялся среди сотен WARNING
        # (Datadog/Sentry alert fatigue).
        logger.error(
            "audit-log query failed (capability_denied events): "
            "exc_type=%s exc_msg=%s — returning stub=True",
            type(exc).__name__,
            exc,
        )
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
        from src.backend.core.plugin_runtime.manifest_toml import (
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
