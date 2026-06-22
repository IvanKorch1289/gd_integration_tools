"""JupyterHub REST API client (TD-024).

Async фасад над JupyterHub API ``/hub/api`` с:
* token-based аутентификацией;
* automatic retry на retriable HTTP-статусы;
* typed request/response через Pydantic models.

Использование::

    from src.backend.core.config.services import jupyter_hub_settings
    from src.backend.infrastructure.clients.external.jupyter_hub import JupyterHubClient

    if not jupyter_hub_settings.enabled:
        raise RuntimeError("JupyterHub integration disabled")

    client = JupyterHubClient(jupyter_hub_settings)
    async with client:
        users = await client.list_users()
        await client.start_server("alice")

Архитектура:
    * ``JupyterHubSettings`` — конфигурация (см. core/config/services/jupyter_hub.py).
    * ``JupyterHubClient`` — этот модуль; wrapper над ``OutboundHttpClient``
      (ADR-NEW-23: все исходящие HTTP через OutboundHttpClient с WAF).
    * Нет дополнительных зависимостей — используем ``httpx`` (уже в проекте).

Ограничения:
    * Named servers поддерживаются через ``server_name`` (default "").
    * JupyterHub < 5.0 может иметь отличия в API; тестировать на целевой версии.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.config.services.jupyter_hub import JupyterHubSettings
from src.backend.core.net.outbound_http import OutboundHttpClient
from src.backend.core.net.waf import WafPolicy
from src.backend.core.logging import get_logger
__all__ = ("JupyterHubClient", "JupyterHubError", "JupyterHubUser", "JupyterHubServer")

_logger = get_logger("infrastructure.jupyter_hub")


class JupyterHubError(Exception):
    """Ошибка взаимодействия с JupyterHub API.

    Attributes:
        message: Человекочитаемое описание.
        status_code: HTTP-статус (если применимо).
        response_body: Тело ответа сервера (если применимо).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class JupyterHubServer:
    """Модель сервера JupyterHub (named или default).

    Attributes:
        name: Имя сервера (пустая строка для default server).
        ready: Готов ли сервер к работе.
        url: URL сервера (если ready).
        pending: Статус pending-операции (spawn/stop и т.п.).
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self.name: str = raw.get("name", "")
        self.ready: bool = raw.get("ready", False)
        self.url: str | None = raw.get("url")
        self.pending: str | None = raw.get("pending")
        self._raw = raw

    def to_dict(self) -> dict[str, Any]:
        return dict(self._raw)


class JupyterHubUser:
    """Модель пользователя JupyterHub.

    Attributes:
        name: Имя пользователя.
        admin: Является ли администратором.
        servers: Словарь серверов {name: JupyterHubServer}.
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self.name: str = raw.get("name", "")
        self.admin: bool = raw.get("admin", False)
        self._raw = raw
        servers_raw: dict[str, Any] = raw.get("servers") or {}
        self.servers: dict[str, JupyterHubServer] = {
            name: JupyterHubServer(data) for name, data in servers_raw.items()
        }

    def to_dict(self) -> dict[str, Any]:
        return dict(self._raw)


class JupyterHubClient:
    """Async HTTP клиент JupyterHub REST API.

    Использует ``OutboundHttpClient`` (ADR-NEW-23) вместо прямого
    ``httpx.AsyncClient`` для соблюдения WAF-политики.

    Args:
        settings: Конфигурация подключения (url, token, timeouts, retries).

    Пример::

        client = JupyterHubClient(jupyter_hub_settings)
        async with client:
            user = await client.get_user("alice")
            if not user.servers.get("").ready:
                await client.start_server("alice")
    """

    def __init__(self, settings: JupyterHubSettings) -> None:
        self._settings = settings
        self._http: OutboundHttpClient | None = None

    async def __aenter__(self) -> JupyterHubClient:
        self._http = self._build_client()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> OutboundHttpClient:
        """Возвращает активный HTTP клиент или создаёт временный."""
        if self._http is None:
            self._http = self._build_client()
        return self._http

    def _build_client(self) -> OutboundHttpClient:
        """Собирает ``OutboundHttpClient`` с WAF-политикой и auth-заголовком."""
        policy = WafPolicy(verify_ssl=self._settings.ssl_verify)
        return OutboundHttpClient(
            base_url=self._settings.base_url.rstrip("/"),
            headers={"Authorization": f"token {self._settings.api_token}"},
            policy=policy,
            max_retries=self._settings.max_retries,
            timeout=self._settings.timeout_seconds,
        )

    # ── Health / Info ──

    async def health_check(self) -> dict[str, Any]:
        """Проверяет доступность Hub (``GET /hub/api``).

        Returns:
            JSON с версией и статусом hub'а.

        Raises:
            JupyterHubError: при недоступности или auth-ошибке.
        """
        return await self._request("GET", "/hub/api/")

    # ── Users ──

    async def list_users(self) -> list[JupyterHubUser]:
        """Возвращает список всех пользователей (``GET /hub/api/users``).

        Returns:
            Список :class:`JupyterHubUser`.
        """
        data = await self._request("GET", "/hub/api/users")
        if not isinstance(data, list):
            raise JupyterHubError("Unexpected response type for list_users")
        return [JupyterHubUser(u) for u in data]

    async def get_user(self, name: str) -> JupyterHubUser:
        """Возвращает пользователя по имени (``GET /hub/api/users/{name}``).

        Args:
            name: Имя пользователя.

        Returns:
            :class:`JupyterHubUser`.

        Raises:
            JupyterHubError: 404 — пользователь не найден.
        """
        data = await self._request("GET", f"/hub/api/users/{name}")
        if not isinstance(data, dict):
            raise JupyterHubError("Unexpected response type for get_user")
        return JupyterHubUser(data)

    async def create_user(self, name: str, *, admin: bool = False) -> JupyterHubUser:
        """Создаёт пользователя (``POST /hub/api/users/{name}``).

        Args:
            name: Имя пользователя.
            admin: Признак администратора.

        Returns:
            Созданный :class:`JupyterHubUser`.

        Raises:
            JupyterHubError: 409 — пользователь уже существует.
        """
        data = await self._request(
            "POST", f"/hub/api/users/{name}", json={"admin": admin}
        )
        if not isinstance(data, dict):
            raise JupyterHubError("Unexpected response type for create_user")
        return JupyterHubUser(data)

    async def delete_user(self, name: str) -> None:
        """Удаляет пользователя (``DELETE /hub/api/users/{name}``).

        Args:
            name: Имя пользователя.

        Raises:
            JupyterHubError: 404 — пользователь не найден.
        """
        await self._request("DELETE", f"/hub/api/users/{name}")

    # ── Servers ──

    async def start_server(self, user_name: str, *, server_name: str = "") -> None:
        """Запускает сервер пользователя (``POST /hub/api/users/{user}/servers/{name}``).

        Args:
            user_name: Имя пользователя.
            server_name: Имя named-сервера (пустая строка — default).

        Raises:
            JupyterHubError: 400 — сервер уже запущен; 404 — пользователь не найден.
        """
        path = f"/hub/api/users/{user_name}/servers"
        if server_name:
            path += f"/{server_name}"
        else:
            path += ""
        await self._request("POST", path)

    async def stop_server(self, user_name: str, *, server_name: str = "") -> None:
        """Останавливает сервер пользователя (``DELETE /hub/api/users/{user}/servers/{name}``).

        Args:
            user_name: Имя пользователя.
            server_name: Имя named-сервера (пустая строка — default).

        Raises:
            JupyterHubError: 404 — пользователь или сервер не найден.
        """
        path = f"/hub/api/users/{user_name}/servers"
        if server_name:
            path += f"/{server_name}"
        else:
            path += ""
        await self._request("DELETE", path)

    async def get_server(
        self, user_name: str, *, server_name: str = ""
    ) -> JupyterHubServer | None:
        """Возвращает состояние сервера через get_user.

        Args:
            user_name: Имя пользователя.
            server_name: Имя named-сервера.

        Returns:
            :class:`JupyterHubServer` или None если сервер не существует.
        """
        user = await self.get_user(user_name)
        return user.servers.get(server_name)

    # ── Low-level ──

    async def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        """Низкоуровневый запрос с логированием и обработкой ошибок."""
        try:
            resp = await self.http.request(method, path, json=json)
        except Exception as exc:
            _logger.warning("JupyterHub request error %s %s: %s", method, path, exc)
            raise JupyterHubError(
                f"JupyterHub request error {method} {path}: {exc}"
            ) from exc

        # JupyterHub возвращает 201/202/204 без тела на spawn/stop;
        # 200 с JSON на GET/POST create.
        if resp.status_code == 204:
            return None
        if resp.content:
            return resp.json()
        return None
