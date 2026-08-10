"""Runtime-состояния приложения (мутабельные, разделяемые между слоями)."""

from src.backend.core.state.runtime import blocked_routes, disabled_feature_flags  # noqa: F401 — re-export

__all__ = ("blocked_routes", "disabled_feature_flags")
