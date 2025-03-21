from typing import List, Pattern, Set

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config.settings import settings


__all__ = ("IPRestrictionMiddleware",)


class IPRestrictionMiddleware(BaseHTTPMiddleware):
    """Middleware для проверки IP-адреса пользователя для административных роутов."""

    def __init__(self, app: ASGIApp):
        from re import compile

        from app.utils.utils import utilities

        super().__init__(app)
        self.allowed_ips: Set[str] = settings.secure.admin_ips
        self.admin_routes: Set[str] = settings.secure.admin_routes
        self.compiled_patterns: List[Pattern] = [
            compile(utilities.convert_pattern(pattern))
            for pattern in self.admin_routes
        ]

    async def dispatch(self, request: Request, call_next):
        # Проверяем, относится ли запрос к административным роутам
        if self._is_admin_route(request.url.path):
            client_ip = request.client.host  # Получаем IP-адрес клиента

            # Проверяем, разрешен ли IP-адрес
            if not self._is_ip_allowed(client_ip):
                raise HTTPException(
                    status_code=403,
                    detail="Доступ запрещен для вашего IP-адреса",
                )

        # Продолжаем обработку запроса
        response = await call_next(request)
        return response

    def _is_admin_route(self, path: str) -> bool:
        """Проверяет, относится ли путь к административным роутам."""
        return any(pattern.match(path) for pattern in self.compiled_patterns)

    def _is_ip_allowed(self, client_ip: str) -> bool:
        """Проверяет, разрешен ли IP-адрес."""
        from ipaddress import ip_address, ip_network

        try:
            client_ip_obj = ip_address(client_ip)
            for allowed_ip in self.allowed_ips:
                # Если это подсеть (например, 192.168.1.0/24)
                if "/" in allowed_ip:
                    network = ip_network(allowed_ip, strict=False)
                    if client_ip_obj in network:
                        return True
                # Если это одиночный IP-адрес
                else:
                    if client_ip == allowed_ip:
                        return True
            return False
        except ValueError:
            # Если IP-адрес некорректен
            return False
