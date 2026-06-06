"""Orders: CRUD для orders."""
from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("OrdersClient",)


class OrdersClient(BaseAPIClient):
    """Клиент для orders CRUD endpoints (orders/all, create, update, delete)."""

    def get_orders(self, page: int = 1, size: int = 50) -> Any:
        return self._request(
            "GET", "/api/v1/orders/all/", params={"page": page, "size": size}
        )

    def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/orders/create/", json=data)

    def update_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/v1/orders/update/{order_id}", json=data)

    def delete_order(self, order_id: int) -> None:
        self._request("DELETE", f"/api/v1/orders/delete/{order_id}")
