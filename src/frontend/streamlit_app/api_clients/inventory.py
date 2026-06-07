"""Inventory: plugins + routes (V11 Plugin Marketplace, Sprint 3)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("InventoryClient",)


class InventoryClient(BaseAPIClient):
    """Клиент для plugins/routes inventory endpoints."""

    def get_plugins_inventory(self) -> dict[str, Any]:
        """GET /api/v1/plugins/inventory.

        Returns:
            ``{"enabled": bool, "plugins": [...], "reason": str | None}``.
            Если loader выключен через feature-flag — ``enabled=False``
            и пустой массив.
        """
        try:
            return self._request("GET", "/api/v1/plugins/inventory")
        except Exception as exc:  # noqa: BLE001
            return {"enabled": False, "plugins": [], "reason": str(exc)}

    def get_routes_inventory(self) -> dict[str, Any]:
        """GET /api/v1/routes/inventory — V11 routes inventory."""
        try:
            return self._request("GET", "/api/v1/routes/inventory")
        except Exception as exc:  # noqa: BLE001
            return {"enabled": False, "routes": [], "reason": str(exc)}
