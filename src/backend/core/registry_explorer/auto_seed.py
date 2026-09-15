"""Auto-seed Streamlit pages from real project data (Sprint 175+ P1.1).

Provides ``StreamlitPageRegistry`` that auto-populates routes/connectors/
actions from existing ``extensions/``, ``routes/``, ``dsl/`` modules —
no manual ``_seed_explorer()`` call needed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.backend.core.registry_explorer.explorer import (
    ActionEntry,
    ConnectorEntry,
    RegistryExplorer,
    RouteEntry,
    get_registry_explorer,
)

logger = logging.getLogger(__name__)

__all__ = (
    "StreamlitPageRegistry",
    "auto_seed_from_project",
    "get_page_registry",
    "reset_page_registry",
)


@dataclass(slots=True)
class StreamlitPageRegistry:
    """Auto-seeded registry для Streamlit pages.

    Attributes:
        explorer: Underlying RegistryExplorer instance.
        auto_seeded: Whether auto-seed was run.
        extensions_dir: Path to extensions/ для discovery.
        routes_dir: Path to routes/ для lightweight integrations.
    """

    explorer: RegistryExplorer
    auto_seeded: bool = False
    extensions_dir: Path | None = None
    routes_dir: Path | None = None
    errors: list[str] = field(default_factory=list)

    def auto_seed(self, force: bool = False) -> int:
        """Auto-seed routes/connectors/actions из project.

        Returns:
            Number of items registered.
        """
        if self.auto_seeded and not force:
            return 0
        count = 0
        try:
            count += self._seed_from_extensions()
        except Exception as exc:  # broad — best effort
            self.errors.append(f"extensions: {exc}")
        try:
            count += self._seed_from_routes()
        except Exception as exc:
            self.errors.append(f"routes: {exc}")
        try:
            count += self._seed_actions_from_dsl()
        except Exception as exc:
            self.errors.append(f"dsl: {exc}")
        self.auto_seeded = True
        logger.info("Auto-seeded %d entries (errors=%d)", count, len(self.errors))
        return count

    def _seed_from_extensions(self) -> int:
        """Scan extensions/ subdirs for connectors."""
        if self.extensions_dir is None:
            # Try default.
            project_root = Path(__file__).resolve().parents[4]
            ext_dir = project_root / "src" / "backend" / "extensions"
        else:
            ext_dir = self.extensions_dir
        if not ext_dir.exists():
            return 0
        count = 0
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        for entry in ext_dir.iterdir():
            if not entry.is_dir():
                continue
            plugin_toml = entry / "plugin.toml"
            if not plugin_toml.exists():
                continue
            try:
                with open(plugin_toml, "rb") as f:
                    meta = tomllib.load(f)
            except Exception as exc:  # broad — best effort
                self.errors.append(f"extensions/{entry.name}: {exc}")
                continue
            name = meta.get("name", entry.name)
            category = meta.get("category", "extension")
            auth = meta.get("auth", "none")
            self.explorer.register_connector(
                ConnectorEntry(
                    name=name,
                    category=category,
                    auth=auth,
                    description=f"Plugin from {entry.name}/",
                )
            )
            count += 1
        return count

    def _seed_from_routes(self) -> int:
        """Scan routes/ subdirs for lightweight integrations."""
        if self.routes_dir is None:
            project_root = Path(__file__).resolve().parents[4]
            r_dir = project_root / "src" / "backend" / "services" / "routes"
        else:
            r_dir = self.routes_dir
        if not r_dir.exists():
            return 0
        count = 0
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        for entry in r_dir.iterdir():
            if not entry.is_dir():
                continue
            route_toml = entry / "route.toml"
            if not route_toml.exists():
                continue
            try:
                with open(route_toml, "rb") as f:
                    meta = tomllib.load(f)
            except Exception as exc:  # broad — best effort
                self.errors.append(f"routes/{entry.name}: {exc}")
                continue
            route_id = meta.get("id", entry.name)
            source = meta.get("source", "unknown")
            owner = meta.get("owner", "")
            self.explorer.register_route(
                RouteEntry(
                    id=route_id, source=source, owner=owner,
                )
            )
            count += 1
        return count

    def _seed_actions_from_dsl(self) -> int:
        """Scan dsl/ subdirs for actions (best-effort)."""
        project_root = Path(__file__).resolve().parents[4]
        dsl_dir = project_root / "src" / "backend" / "dsl" / "actions"
        if not dsl_dir.exists():
            return 0
        count = 0
        for entry in dsl_dir.iterdir():
            if not entry.is_file() or entry.suffix != ".py":
                continue
            if entry.name.startswith("_") or entry.name == "__init__.py":
                continue
            action_name = entry.stem
            self.explorer.register_action(
                ActionEntry(
                    name=action_name,
                    side_effect="read",
                    description=f"Auto-discovered from {entry.name}",
                )
            )
            count += 1
        return count


def auto_seed_from_project(
    extensions_dir: Path | None = None,
    routes_dir: Path | None = None,
) -> StreamlitPageRegistry:
    """Standalone auto-seed для project.

    Args:
        extensions_dir: Path to extensions/ (default: src/backend/extensions).
        routes_dir: Path to routes/ (default: src/backend/services/routes).

    Returns:
        StreamlitPageRegistry instance с auto-seeded data.
    """
    explorer = get_registry_explorer()
    reg = StreamlitPageRegistry(
        explorer=explorer,
        extensions_dir=extensions_dir,
        routes_dir=routes_dir,
    )
    reg.auto_seed(force=True)
    return reg


# Module-level singleton.
_page_registry: StreamlitPageRegistry | None = None


def get_page_registry() -> StreamlitPageRegistry:
    """Get singleton page registry (auto-seeds on first call)."""
    global _page_registry
    if _page_registry is None:
        _page_registry = auto_seed_from_project()
    return _page_registry


def reset_page_registry() -> None:
    """Reset the page registry singleton (test-only)."""
    global _page_registry
    _page_registry = None
