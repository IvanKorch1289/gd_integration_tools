"""Orders: CRUD для orders."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("OrdersClient",)


class OrdersClient(BaseAPIClient):
    """Клиент для orders CRUD endpoints (orders/all, create, update, delete)."""

    def get_orders(self, page: int = 1, size: int = 50) -> Any:
        """Получить список orders с pagination (``page``, ``size``)."""
        return self._request(
            "GET", "/api/v1/orders/all/", params={"page": page, "size": size}
        )

    def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        """Создать новый order; вернуть созданную запись."""
        return self._request("POST", "/api/v1/orders/create/", json=data)

    def update_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Обновить order по ``order_id`` с новыми данными ``data``."""
        return self._request("PUT", f"/api/v1/orders/update/{order_id}", json=data)

    def delete_order(self, order_id: int) -> None:
        """Удалить order по ``order_id``."""
        self._request("DELETE", f"/api/v1/orders/delete/{order_id}")
