"""Runtime-состояния приложения.

Мутабельные переменные, разделяемые между слоями
(middleware, сервисы, entrypoints).
"""

__all__ = ("blocked_routes",)


blocked_routes: set[str] = set()
