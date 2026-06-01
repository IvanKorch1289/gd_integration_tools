"""HTTP-клиент Plugin Marketplace для Streamlit-страницы 60_Plugin_Marketplace.

Обеспечивает три публичные функции:

* :func:`list_plugins` — получить список установленных плагинов (GET).
* :func:`get_plugin_manifest` — получить manifest конкретного плагина (GET).
* :func:`toggle_plugin` — включить / отключить плагин (POST).

Все функции содержат mock-fallback: если backend недоступен (ConnectError /
ConnectionError / любой httpx-транспортный сбой), возвращаются заглушечные
данные, достаточные для dev-запуска без бэкенда.

Lazy-import httpx: модуль не требует httpx в окружении без тестов / UI.
"""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.config import (
    API_TIMEOUT_MEDIUM,
    API_TIMEOUT_SHORT,
    get_api_base_url,
)

__all__ = ("get_plugin_manifest", "list_plugins", "toggle_plugin")

_BASE_URL = get_api_base_url().rstrip("/")

# ---------------------------------------------------------------------------
# Mock-данные (fallback когда backend недоступен)
# ---------------------------------------------------------------------------
_MOCK_PLUGINS: list[dict[str, Any]] = [
    {
        "name": "core_entities",
        "version": "1.0.0",
        "status": "active",
        "capabilities": ["db.read", "db.write"],
        "routes_count": 4,
        "actions_count": 12,
        "tenant_aware": True,
        "description": "Базовые сущности (users/orders/orderkinds/files)",
    },
    {
        "name": "credit_workflow",
        "version": "0.9.1",
        "status": "active",
        "capabilities": ["db.read", "db.write", "workflow.invoke"],
        "routes_count": 2,
        "actions_count": 5,
        "tenant_aware": True,
        "description": "Кредитный конвейер (reference plugin)",
    },
    {
        "name": "notification_hub",
        "version": "0.3.0",
        "status": "disabled",
        "capabilities": [
            "net.outbound.smtp:internal",
            "net.outbound.telegram:external",
        ],
        "routes_count": 1,
        "actions_count": 3,
        "tenant_aware": False,
        "description": "Уведомления через Apprise (Slack/Telegram/Email)",
    },
    {
        "name": "audit_clickhouse",
        "version": "0.2.0",
        "status": "disabled",
        "capabilities": ["db.write", "net.outbound.clickhouse:internal"],
        "routes_count": 0,
        "actions_count": 2,
        "tenant_aware": True,
        "description": "Audit trail в ClickHouse",
    },
]

_MOCK_MANIFESTS: dict[str, dict[str, Any]] = {
    p["name"]: {
        "name": p["name"],
        "version": p["version"],
        "requires_core": ">=1.0.0",
        "capabilities": p["capabilities"],
        "tenant_aware": p["tenant_aware"],
        "provides": {
            "actions": [f"{p['name']}.action_{i}" for i in range(p["actions_count"])],
            "routes": [f"{p['name']}/route_{i}" for i in range(p["routes_count"])],
        },
        "description": p["description"],
    }
    for p in _MOCK_PLUGINS
}


def _is_transport_error(exc: Exception) -> bool:
    """Проверяет, является ли исключение транспортной ошибкой httpx.

    Args:
        exc: Исключение для проверки.

    Returns:
        True если это httpx.TransportError или OSError (backend недоступен).
    """
    try:
        import httpx  # noqa: PLC0415

        return isinstance(exc, (httpx.TransportError, httpx.ConnectError, OSError))
    except ImportError:
        return isinstance(exc, OSError)


def list_plugins(status_filter: str = "all") -> list[dict[str, Any]]:
    """Возвращает список установленных плагинов с backend.

    Выполняет GET /api/v1/admin/plugins/list. При недоступности backend
    возвращает mock-список для dev-окружения.

    Args:
        status_filter: Фильтр по статусу — ``"all"``, ``"active"``
                       или ``"disabled"``. По умолчанию ``"all"``.

    Returns:
        Список словарей с ключами: name, version, status, capabilities,
        routes_count, actions_count, tenant_aware, description.
    """
    try:
        import httpx  # noqa: PLC0415

        with httpx.Client(timeout=API_TIMEOUT_SHORT) as client:
            response = client.get(f"{_BASE_URL}/api/v1/admin/plugins/list")
            response.raise_for_status()
            data = response.json()
            plugins: list[dict[str, Any]] = (
                data
                if isinstance(data, list)
                else data.get("plugins", data.get("items", []))
            )
    except Exception as _:  # noqa: BLE001
        plugins = list(_MOCK_PLUGINS)

    if status_filter != "all":
        plugins = [p for p in plugins if p.get("status") == status_filter]

    return plugins


def get_plugin_manifest(name: str) -> dict[str, Any] | None:
    """Возвращает manifest плагина по имени.

    Выполняет GET /api/v1/admin/plugins/{name}/manifest. При HTTP 404
    или недоступности backend возвращает None или mock-manifest из
    локального словаря.

    Args:
        name: Имя плагина (например, ``"core_entities"``).

    Returns:
        Словарь manifest плагина или None если плагин не найден.
    """
    try:
        import httpx  # noqa: PLC0415

        with httpx.Client(timeout=API_TIMEOUT_SHORT) as client:
            response = client.get(f"{_BASE_URL}/api/v1/admin/plugins/{name}/manifest")
            if response.status_code == 404:  # noqa: PLR2004
                return None
            response.raise_for_status()
            return response.json()
    except Exception as _:  # noqa: BLE001
        return _MOCK_MANIFESTS.get(name)


def toggle_plugin(name: str, active: bool) -> bool:  # noqa: FBT001
    """Включает или отключает плагин через backend.

    Выполняет POST /api/v1/admin/plugins/{name}/toggle. При недоступности
    backend возвращает True (оптимистичный fallback для dev-окружения).

    Args:
        name: Имя плагина (например, ``"notification_hub"``).
        active: True — включить плагин, False — отключить.

    Returns:
        True если операция успешна (или backend недоступен — dev-fallback),
        False при HTTP-ошибке (4xx/5xx) от backend.
    """
    body: dict[str, Any] = {"name": name, "active": active}
    try:
        import httpx  # noqa: PLC0415

        with httpx.Client(timeout=API_TIMEOUT_MEDIUM) as client:
            response = client.post(
                f"{_BASE_URL}/api/v1/admin/plugins/{name}/toggle", json=body
            )
            return response.status_code < 400  # noqa: PLR2004
    except Exception as _:  # noqa: BLE001
        # dev-fallback: считаем операцию успешной
        return True
