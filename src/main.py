from fastapi import FastAPI

from src.core.config.settings import settings
from src.infrastructure.application.app_factory import create_app

app: FastAPI = create_app()


def run() -> None:
    import uvicorn

    uvicorn_kwargs = {
        "app": "main:app",
        "host": settings.app.host,
        "port": settings.app.port,
        "log_level": "debug" if settings.app.debug_mode else "info",
        "use_colors": settings.app.environment != "production",
        "limit_concurrency": 1000,
        "timeout_keep_alive": 30,
    }

    if settings.app.environment in {"development", "testing"}:
        uvicorn_kwargs["reload"] = settings.app.debug_mode
    else:
        uvicorn_kwargs["workers"] = 1

    uvicorn.run(**uvicorn_kwargs)


if __name__ == "__main__":
    run()
