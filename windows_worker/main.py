"""Windows worker — FastAPI app для COM + desktop RPA операций.

Wave ``[wave:s6/k3-com-windows-sidecar]`` (rename ``windows-sidecar`` →
``windows_worker``: Sprint 8 AUDIT-3, 2026-05-15).

Назначение: запускается ТОЛЬКО на Windows-worker (docker-compose
``windows-worker`` service). Принимает HTTP-запросы от основного backend
(см. ``services/rpa/com_sidecar_client.py``) и через ``pywin32`` /
``comtypes`` / ``pywinauto`` (Sprint 8B) вызывает COM-объекты и
desktop-RPA-сценарии.

Архитектура:

* основной backend (Linux/MacOS) использует ``.call_com(worker, method,
  params)`` DSL-шаг → REST POST ``/com/call`` к worker'у;
* worker (Windows) парсит request, вызывает COM-метод через
  ``win32com.client.Dispatch(worker)``, возвращает JSON-result;
* при недоступности pywin32 (Linux dev — обычный случай) endpoint
  возвращает 503 ``service_unavailable``.

Запуск (Windows):

    uvicorn windows_worker.main:app --host 0.0.0.0 --port 9001

Запуск через docker:

    docker compose -f docker-compose.windows-worker.yml up windows-worker

Feature flag (backend-side): ``feature_flags.com_sidecar_enabled``.
"""

from __future__ import annotations

import logging
import sys as _sys

from fastapi import FastAPI

from windows_worker.handlers.com_handler import router as com_router
from windows_worker.handlers.desktop_rpa_handler import router as rpa_router

__all__ = ("app", "create_app")

_logger = logging.getLogger("windows_worker")


def create_app() -> FastAPI:
    """Создаёт FastAPI app для Windows worker.

    Returns:
        FastAPI с подключёнными ``/com`` + ``/rpa`` router'ами.
    """
    application = FastAPI(
        title="GD Integration Tools — Windows Worker",
        description=(
            "REST-фасад для COM-операций (pywin32 + comtypes) и desktop "
            "RPA (pywinauto, Sprint 8B). Запускается ТОЛЬКО на Windows-host."
        ),
        version="0.1.0",
    )
    application.include_router(com_router, prefix="/com", tags=["COM"])
    application.include_router(rpa_router, prefix="/rpa", tags=["RPA"])

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Health endpoint — возвращает статус platform и pywin32."""
        platform_ok = _sys.platform == "win32"
        pywin32_ok = False
        if platform_ok:
            try:
                import win32com.client  # noqa: F401, PLC0415

                pywin32_ok = True
            except ImportError:
                pywin32_ok = False
        return {
            "platform": _sys.platform,
            "platform_ok": "yes" if platform_ok else "no",
            "pywin32_ok": "yes" if pywin32_ok else "no",
            "status": "ok" if platform_ok and pywin32_ok else "degraded",
        }

    return application


app = create_app()
