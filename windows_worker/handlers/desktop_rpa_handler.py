"""Desktop RPA handler — scaffold для Sprint 8B K3 W4 (pywinauto).

Wave ``[wave:s8/backbone-audit-1-and-3]`` — scaffold создан в Sprint 8A;
production-реализация мигрирует в Sprint 8B (K3 W4 ``rpa-windows-desktop``).

Endpoints (scaffold, всегда 503 до Sprint 8B):

* ``POST /rpa/click`` — клик в desktop UI (pywinauto Application/UIA/Win32 backend);
* ``POST /rpa/type``  — ввод текста в активный controls;
* ``POST /rpa/screenshot`` — снимок экрана (для AI-vision integration).

Безопасность (Sprint 8B):

* Whitelist разрешённых ``app.exe`` (предотвращение arbitrary GUI control);
* Workspace isolation (только app'ы, прописанные в plugin capabilities);
* Аудит через единый ``audit_log`` backend-side.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

__all__ = ("router", "DesktopClickRequest", "DesktopTypeRequest")

_logger = logging.getLogger("windows_worker.rpa")

router = APIRouter()


class DesktopClickRequest(BaseModel):
    """Запрос на клик по UI-элементу.

    Атрибуты:
        app: Путь к exe или ProcessID запущенного приложения.
        selector: pywinauto-spec (title=, control_type=, automation_id=).
        button: Кнопка мыши (left/right/middle).
        timeout: Таймаут поиска control в секундах.
    """

    app: str = Field(..., description="Путь к exe или ProcessID")
    selector: dict[str, Any] = Field(..., description="pywinauto selector")
    button: str = Field(default="left", pattern="^(left|right|middle)$")
    timeout: float = Field(default=10.0, ge=0.1, le=60.0)


class DesktopTypeRequest(BaseModel):
    """Запрос на ввод текста в активный control.

    Атрибуты:
        app: Путь к exe или ProcessID запущенного приложения.
        selector: pywinauto-spec для control'а.
        text: Текст для ввода (поддерживает special keys через {ENTER}, {TAB}).
        timeout: Таймаут операции в секундах.
    """

    app: str
    selector: dict[str, Any]
    text: str
    timeout: float = Field(default=10.0, ge=0.1, le=60.0)


def _is_pywinauto_available() -> bool:
    """Проверяет наличие pywinauto (только на Windows)."""
    if sys.platform != "win32":
        return False
    try:
        import pywinauto  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


@router.post("/click")
async def desktop_click(request: DesktopClickRequest) -> dict[str, Any]:
    """Scaffold endpoint — production-реализация в Sprint 8B K3 W4."""
    if not _is_pywinauto_available():
        raise HTTPException(
            status_code=503,
            detail="pywinauto не установлен. Sidecar работает только на Windows.",
        )
    raise HTTPException(
        status_code=501,
        detail=(
            "Desktop RPA scaffold — production handler планируется в "
            "Sprint 8B K3 W4 [wave:s8b/k3-w4-rpa-windows-desktop]."
        ),
    )


@router.post("/type")
async def desktop_type(request: DesktopTypeRequest) -> dict[str, Any]:
    """Scaffold endpoint — production-реализация в Sprint 8B K3 W4."""
    if not _is_pywinauto_available():
        raise HTTPException(status_code=503, detail="pywinauto не установлен")
    raise HTTPException(
        status_code=501,
        detail=(
            "Desktop RPA scaffold — production handler планируется в "
            "Sprint 8B K3 W4 [wave:s8b/k3-w4-rpa-windows-desktop]."
        ),
    )


@router.get("/info")
async def desktop_info() -> dict[str, Any]:
    """Возвращает статус scaffold-handler'а."""
    return {
        "platform": sys.platform,
        "pywinauto_available": _is_pywinauto_available(),
        "scaffold": True,
        "production_wave": "s8b/k3-w4-rpa-windows-desktop",
    }
