"""Express entrypoint — приёмник команд и callback от BotX."""

from src.backend.entrypoints.express.router import router  # noqa: F401 — re-export as router  # noqa: F401 — re-export

__all__ = ("router",)
