"""Runtime-состояния приложения (мутабельные, разделяемые между слоями)."""

from src.core.state.runtime import blocked_routes, disabled_feature_flags

__all__ = ("blocked_routes", "disabled_feature_flags")
