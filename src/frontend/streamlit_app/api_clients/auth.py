"""Auth API client — login + auth methods.

S169: Frontend auth support. Используется LoginClient для вызова
``POST /auth/login`` и ``GET /auth/methods``.
"""

from __future__ import annotations

from typing import Any, Literal

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("AuthClient", "AuthMethods", "LoginResponse")


class AuthMethods:
    """Вспомогательный класс для GET /auth/methods."""

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Нормализует payload: methods, default_method, deprecations."""
        return {
            "methods": payload.get("methods", []),
            "ldap_enabled": payload.get("ldap_enabled", False),
            "password_enabled": payload.get("password_enabled", True),
            "default_method": payload.get("default_method", "password"),
            "deprecations": payload.get("deprecations", {}),
        }


class LoginResponse:
    """Typed wrapper для response от POST /auth/login."""

    __slots__ = (
        "access_token",
        "token_type",
        "auth_method",
        "username",
        "is_superuser",
        "expires_in",
    )

    def __init__(self, payload: dict[str, Any]) -> None:
        self.access_token: str = payload["access_token"]
        self.token_type: str = payload.get("token_type", "bearer")
        self.auth_method: str = payload["auth_method"]
        self.username: str = payload["username"]
        self.is_superuser: bool = payload.get("is_superuser", False)
        self.expires_in: int = payload.get("expires_in", 3600)


class AuthClient(BaseAPIClient):
    """Клиент для auth-эндпоинтов.

    Наследует :class:`BaseAPIClient` (retry + Bearer auth).
    """

    def get_methods(self) -> dict[str, Any]:
        """``GET /auth/methods`` — список доступных auth methods.

        Не требует auth (вызывается до login).
        """
        payload = self.get("/api/v1/auth/methods")
        return AuthMethods.from_payload(payload)

    def login(
        self, *, method: Literal["password", "ldap"], username: str, password: str
    ) -> LoginResponse:
        """``POST /auth/login`` — аутентификация по username/password.

        Args:
            method: ``"password"`` или ``"ldap"`` (per S58 W6d).
            username: Имя пользователя.
            password: Пароль.

        Returns:
            :class:`LoginResponse` с JWT token.

        Raises:
            PermissionError: 401 — invalid credentials.
            httpx.HTTPStatusError: 4xx/5xx — другие ошибки.
        """
        payload = self.post(
            "/api/v1/auth/login",
            json={"method": method, "username": username, "password": password},
        )
        return LoginResponse(payload)

    def introspect(self) -> dict[str, Any]:
        """``GET /auth/introspect`` — проверить валидность текущего токена.

        Требует Bearer auth (token уже должен быть установлен через ``set_token``).
        """
        return self.get("/api/v1/auth/introspect")
