"""Desktop RPA handler (Wave [wave:s8/k3-rpa-windows-desktop]).

Production-реализация Win32/UIA автоматизации поверх pywinauto. Запускается
ТОЛЬКО на Windows-worker (docker-compose ``windows-worker`` service).

Endpoints:

* ``POST /rpa/click`` — клик в desktop UI (pywinauto Application/UIA backend).
* ``POST /rpa/type``  — ввод текста в активный control.
* ``POST /rpa/screenshot`` — снимок экрана / окна (для AI-vision).
* ``GET /rpa/info`` — статус (для health-check).

Безопасность:

* Whitelist разрешённых ``app.exe`` через env ``DESKTOP_RPA_ALLOWED_APPS``
  (запятая-разделённый список); ``*`` отключает фильтр (только dev).
* На non-Windows платформе все endpoints возвращают 503 (sidecar не
  функциональный, основной backend это ожидает и фолбэчится).
"""

from __future__ import annotations

import base64
import logging
import ntpath
import os
import sys
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

__all__ = (
    "router",
    "DesktopClickRequest",
    "DesktopTypeRequest",
    "DesktopScreenshotRequest",
)

_logger = logging.getLogger("windows_worker.rpa")

router = APIRouter()


class DesktopClickRequest(BaseModel):
    """Запрос на клик по UI-элементу.

    Атрибуты:
        app: Путь к exe или ProcessID запущенного приложения.
        selector: pywinauto-spec (title=, control_type=, automation_id=).
        button: Кнопка мыши (left/right/middle).
        backend: Win32 (legacy) или UIA (modern apps); default UIA.
        timeout: Таймаут поиска control в секундах.
    """

    app: str = Field(..., description="Путь к exe или ProcessID")
    selector: dict[str, Any] = Field(..., description="pywinauto selector")
    button: Literal["left", "right", "middle"] = Field(default="left")
    backend: Literal["uia", "win32"] = Field(default="uia")
    timeout: float = Field(default=10.0, ge=0.1, le=60.0)


class DesktopTypeRequest(BaseModel):
    """Запрос на ввод текста в активный control.

    Атрибуты:
        app: Путь к exe или ProcessID запущенного приложения.
        selector: pywinauto-spec для control'а.
        text: Текст для ввода (поддерживает special keys через {ENTER}, {TAB}).
        backend: Win32 / UIA.
        timeout: Таймаут операции в секундах.
    """

    app: str
    selector: dict[str, Any]
    text: str
    backend: Literal["uia", "win32"] = Field(default="uia")
    timeout: float = Field(default=10.0, ge=0.1, le=60.0)


class DesktopScreenshotRequest(BaseModel):
    """Запрос на скриншот экрана или окна приложения.

    Атрибуты:
        app: Опц. путь к exe — снимается окно приложения. ``None`` — full-screen.
        backend: Win32 / UIA (важно только при ``app``).
        timeout: Таймаут поиска окна в секундах.
    """

    app: str | None = None
    backend: Literal["uia", "win32"] = Field(default="uia")
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


def _check_app_whitelist(app: str) -> None:
    """Проверяет, что ``app`` входит в DESKTOP_RPA_ALLOWED_APPS whitelist.

    Raises:
        HTTPException(403): если app не разрешён политикой.
    """
    allowed_raw = os.environ.get("DESKTOP_RPA_ALLOWED_APPS", "")
    allowed = [a.strip() for a in allowed_raw.split(",") if a.strip()]
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "DESKTOP_RPA_ALLOWED_APPS не настроен; sidecar отказывает по "
                "умолчанию (no-default-allow для arbitrary GUI control)."
            ),
        )
    if "*" in allowed:
        return

    # normalize: извлекаем basename и приводим к lowercase для case-insensitive compare.
    # Это предотвращает substring-bypass: "C:\Windows\notepad.exe" vs "notepad"
    # не должны совпадать как "C:\notepad_notepad.exe".
    app_basename = ntpath.basename(app).lower()
    normalized = app_basename.rstrip(".exe")

    # Support both "notepad" and "notepad.exe" in allowlist uniformly
    allowed_normalized = {a.lower().rstrip(".exe") for a in allowed}

    if normalized not in allowed_normalized:
        raise HTTPException(
            status_code=403,
            detail=f"App {app!r} не входит в whitelist (DESKTOP_RPA_ALLOWED_APPS).",
        )


def _connect_or_start(app: str, *, backend: str, timeout: float):  # noqa: ANN202
    """Подключается к запущенному приложению или стартует exe.

    Args:
        app: Путь к exe или PID (digits only).
        backend: pywinauto backend (``'win32'`` или ``'uia'``).
        timeout: Таймаут подключения в секундах.

    Returns:
        ``Application``-объект pywinauto (connect или start).

    Raises:
        pywinauto.MatchError: Приложение не найдено и не может быть запущено.
        TimeoutError: Превышен таймаут ожидания.
    """
    from pywinauto import Application  # noqa: PLC0415

    application = Application(backend=backend)
    if app.isdigit():
        return application.connect(process=int(app), timeout=timeout)
    try:
        return application.connect(path=app, timeout=timeout)
    except Exception as _:  # noqa: BLE001 — pywinauto.MatchError / TimeoutError
        return application.start(app)


@router.post("/click")
async def desktop_click(request: DesktopClickRequest) -> dict[str, Any]:
    """Кликает по UI-элементу через pywinauto."""
    if not _is_pywinauto_available():
        raise HTTPException(
            status_code=503,
            detail="pywinauto не установлен. Sidecar работает только на Windows.",
        )
    _check_app_whitelist(request.app)
    try:
        application = _connect_or_start(
            request.app, backend=request.backend, timeout=request.timeout
        )
        window = application.window(**request.selector)
        window.wait("visible", timeout=request.timeout)
        click_method = {
            "left": window.click_input,
            "right": window.right_click_input,
            "middle": window.click_input,
        }[request.button]
        click_method()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _logger.warning("desktop_click failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"desktop_click error: {exc}")
    return {"ok": True, "action": "click", "button": request.button}


@router.post("/type")
async def desktop_type(request: DesktopTypeRequest) -> dict[str, Any]:
    """Вводит текст в control."""
    if not _is_pywinauto_available():
        raise HTTPException(status_code=503, detail="pywinauto не установлен")
    _check_app_whitelist(request.app)
    try:
        application = _connect_or_start(
            request.app, backend=request.backend, timeout=request.timeout
        )
        window = application.window(**request.selector)
        window.wait("visible", timeout=request.timeout)
        window.type_keys(request.text, with_spaces=True)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _logger.warning("desktop_type failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"desktop_type error: {exc}")
    return {"ok": True, "action": "type", "chars": len(request.text)}


@router.post("/screenshot")
async def desktop_screenshot(request: DesktopScreenshotRequest) -> dict[str, Any]:
    """Возвращает скриншот в base64-png.

    При ``app=None`` — снимок всего экрана (через PIL.ImageGrab).
    Иначе — снимок окна приложения (window.capture_as_image()).
    """
    if not _is_pywinauto_available():
        raise HTTPException(status_code=503, detail="pywinauto не установлен")
    if request.app is not None:
        _check_app_whitelist(request.app)
    try:
        from io import BytesIO  # noqa: PLC0415

        if request.app is None:
            from PIL import ImageGrab  # noqa: PLC0415

            img = ImageGrab.grab()
        else:
            application = _connect_or_start(
                request.app, backend=request.backend, timeout=request.timeout
            )
            window = application.top_window()
            img = window.capture_as_image()
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _logger.warning("desktop_screenshot failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"desktop_screenshot error: {exc}")
    return {"ok": True, "format": "png", "base64": encoded}


@router.get("/info")
async def desktop_info() -> dict[str, Any]:
    """Возвращает статус handler'а (для health-check / discovery)."""
    return {
        "platform": sys.platform,
        "pywinauto_available": _is_pywinauto_available(),
        "production": True,
        "wave": "s8/k3-rpa-windows-desktop",
        "whitelist_configured": bool(
            os.environ.get("DESKTOP_RPA_ALLOWED_APPS", "").strip()
        ),
    }
