"""Runtime-состояния приложения.

Мутабельные переменные, разделяемые между слоями
(middleware, сервисы, entrypoints).
"""

__all__ = ("blocked_routes", "disabled_feature_flags")


blocked_routes: set[str] = set()

disabled_feature_flags: set[str] = set()
