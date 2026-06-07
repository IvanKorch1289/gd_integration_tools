"""Feature flags: list/toggle + runtime overrides (per-tenant)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("FlagsClient",)


class FlagsClient(BaseAPIClient):
    """Клиент для feature-flags endpoints (list, toggle, overrides)."""

    def get_flags(self) -> list[dict[str, Any]]:
        try:
            return self._request("GET", "/api/v1/admin/feature-flags")
        except Exception:  # noqa: BLE001
            return []

    def toggle_flag(self, name: str, enabled: bool) -> bool:
        try:
            self._request(
                "POST",
                f"/api/v1/admin/feature-flags/{name}/toggle",
                json={"enabled": enabled},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def list_overrides(self) -> dict[str, Any]:
        """Sprint 17 K5 W1 (D9): runtime overrides — global + per-tenant.

        Returns ``{"global": {...}, "per_tenant": {tenant_id: {...}}}``
        или пустой dict при недоступности backend.
        """
        try:
            return self._request("GET", "/api/v1/admin/feature-flags")
        except Exception:  # noqa: BLE001
            return {}

    def set_override(
        self, flag: str, value: Any, tenant_id: str | None = None, actor: str = "ui"
    ) -> dict[str, Any] | None:
        """Sprint 17 K5 W1 (D9): установить runtime override (опц. per-tenant)."""
        try:
            return self._request(
                "PUT",
                f"/api/v1/admin/feature-flags/{flag}",
                json={"value": value, "tenant_id": tenant_id, "actor": actor},
            )
        except Exception:  # noqa: BLE001
            return None

    def clear_override(
        self, flag: str, tenant_id: str | None = None, actor: str = "ui"
    ) -> dict[str, Any] | None:
        """Sprint 17 K5 W1 (D9): снять runtime override (вернуть к static-default)."""
        try:
            params: dict[str, Any] = {"actor": actor}
            if tenant_id is not None:
                params["tenant_id"] = tenant_id
            return self._request(
                "DELETE", f"/api/v1/admin/feature-flags/{flag}", params=params
            )
        except Exception:  # noqa: BLE001
            return None
