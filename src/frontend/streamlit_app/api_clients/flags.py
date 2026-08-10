"""Feature flags: list/toggle + runtime overrides (per-tenant)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("FlagsClient",)


class FlagsClient(BaseAPIClient):
    """Клиент для feature-flags endpoints (list, toggle, overrides)."""

    def get_flags(self) -> list[dict[str, Any]]:
        """Метод get_flags (см. signature)."""
        try:
            return self._request("GET", "/api/v1/admin/feature-flags")
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as flags_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1070: narrow exceptions + observability.
            # ConnectionError/TimeoutError — server unreachable, RuntimeError
            # — API failure, ValueError — invalid response, TypeError —
            # wrong type.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_flags_client.get_failed",
                extra={"error": str(flags_exc)},
            )
            return []

    def toggle_flag(self, name: str, enabled: bool) -> bool:
        """Метод toggle_flag (см. signature)."""
        try:
            self._request(
                "POST",
                f"/api/v1/admin/feature-flags/{name}/toggle",
                json={"enabled": enabled},
            )
            return True
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as toggle_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1070: см. выше — mirror для toggle.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_flags_client.toggle_failed",
                extra={"name": name, "error": str(toggle_exc)},
            )
            return False

    def list_overrides(self) -> dict[str, Any]:
        """Sprint 17 K5 W1 (D9): runtime overrides — global + per-tenant.

        Returns ``{"global": {...}, "per_tenant": {tenant_id: {...}}}``
        или пустой dict при недоступности backend.
        """
        try:
            return self._request("GET", "/api/v1/admin/feature-flags")
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as list_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1070: см. выше — mirror для list_overrides.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_flags_client.list_overrides_failed",
                extra={"error": str(list_exc)},
            )
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
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as set_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1070: см. выше — mirror для set_override.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_flags_client.set_override_failed",
                extra={"flag": flag, "error": str(set_exc)},
            )
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
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as clear_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1070: см. выше — mirror для clear_override.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_flags_client.clear_override_failed",
                extra={"flag": flag, "error": str(clear_exc)},
            )
            return None
