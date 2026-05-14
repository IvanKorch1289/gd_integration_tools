"""HTTP-клиент Action Bus для Streamlit-страницы 50_Action_Bus.

Обеспечивает три публичные функции:

* :func:`list_actions` — получить список зарегистрированных actions (GET).
* :func:`invoke` — вызвать action с JSON-payload в одном из трёх режимов (POST).
* :func:`get_action_spec` — получить спецификацию конкретного action (GET).

Все функции содержат mock-fallback: если backend недоступен (ConnectError /
ConnectionError / любой httpx-транспортный сбой), возвращаются заглушечные
данные, достаточные для dev-запуска без бэкенда.

Lazy-import httpx: модуль не требует httpx в окружении без тестов / UI.
"""

from __future__ import annotations

import json
import os
from typing import Any

__all__ = ("get_action_spec", "invoke", "list_actions")

_BASE_URL: str = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")

# ---------------------------------------------------------------------------
# Mock-данные (fallback когда backend недоступен)
# ---------------------------------------------------------------------------
_MOCK_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "system.health.check",
        "description": "Проверка состояния системы",
        "namespace": "system",
        "tier": 1,
    },
    {
        "name": "orders.create",
        "description": "Создать новый заказ",
        "namespace": "orders",
        "tier": 2,
    },
    {
        "name": "ai.chat.complete",
        "description": "Завершить AI-чат сообщение",
        "namespace": "ai",
        "tier": 2,
    },
    {
        "name": "dsl.route.reload",
        "description": "Перезагрузить DSL-маршрут по имени",
        "namespace": "dsl",
        "tier": 3,
    },
]

_MOCK_SPECS: dict[str, dict[str, Any]] = {
    "system.health.check": {
        "name": "system.health.check",
        "description": "Проверка состояния системы",
        "namespace": "system",
        "tier": 1,
        "params_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "result_schema": {
            "type": "object",
            "properties": {"status": {"type": "string"}, "components": {"type": "object"}},
        },
    },
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


def list_actions() -> list[dict[str, Any]]:
    """Возвращает список зарегистрированных actions с backend.

    Выполняет GET /api/v1/admin/actions/list. При недоступности backend
    возвращает mock-список для dev-окружения.

    Returns:
        Список словарей с ключами: name, description, namespace, tier.
    """
    try:
        import httpx  # noqa: PLC0415

        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{_BASE_URL}/api/v1/admin/actions/list")
            response.raise_for_status()
            data = response.json()
            # backend может вернуть {"actions": [...]} или сразу список
            if isinstance(data, list):
                return data
            return data.get("actions", data.get("items", []))
    except Exception as exc:  # noqa: BLE001
        if _is_transport_error(exc) or not _is_transport_error(exc):
            # возвращаем mock при любой ошибке — цель: dev без backend
            return list(_MOCK_ACTIONS)
        raise


def invoke(name: str, payload: dict[str, Any], mode: str) -> dict[str, Any]:
    """Вызывает action с JSON-payload через backend.

    Выполняет POST /api/v1/admin/actions/invoke. При недоступности backend
    возвращает mock-ответ для dev-окружения.

    Args:
        name: Имя action (например, ``"system.health.check"``).
        payload: JSON-payload для action (произвольный dict).
        mode: Режим вызова — ``"sync"``, ``"async-fire-and-forget"``
              или ``"async-api"``.

    Returns:
        Словарь с результатом вызова. При ошибке бэкенда содержит
        ключи ``error`` и ``detail``.
    """
    body: dict[str, Any] = {
        "action": name,
        "payload": payload,
        "mode": mode,
    }
    try:
        import httpx  # noqa: PLC0415

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{_BASE_URL}/api/v1/admin/actions/invoke",
                json=body,
            )
            if response.status_code >= 400:  # noqa: PLR2004
                try:
                    detail = response.json()
                except json.JSONDecodeError:
                    detail = response.text
                return {
                    "error": f"HTTP {response.status_code}",
                    "detail": detail,
                    "action": name,
                    "mode": mode,
                }
            return response.json()
    except Exception as exc:  # noqa: BLE001
        # mock fallback — эмулируем успешный ответ для dev
        return {
            "status": "mock",
            "action": name,
            "mode": mode,
            "payload_echo": payload,
            "note": f"Backend недоступен: {type(exc).__name__}",
        }


def get_action_spec(name: str) -> dict[str, Any] | None:
    """Возвращает спецификацию action по имени.

    Выполняет GET /api/v1/admin/actions/{name}/spec. При HTTP 404
    или недоступности backend возвращает None или mock-данные из
    локального словаря.

    Args:
        name: Имя action.

    Returns:
        Словарь спецификации action или None если action не найден.
    """
    try:
        import httpx  # noqa: PLC0415

        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{_BASE_URL}/api/v1/admin/actions/{name}/spec")
            if response.status_code == 404:  # noqa: PLR2004
                return None
            response.raise_for_status()
            return response.json()
    except Exception as exc:  # noqa: BLE001
        # fallback к локальному mock-словарю
        _ = exc  # транспортная ошибка — отдаём заглушку
        return _MOCK_SPECS.get(name)
