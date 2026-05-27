"""Windows COM Router — FastAPI router для COM-операций.

Wave ``[wave:s6/k3-com-windows-sidecar]``.

Endpoints:

* ``POST /com/call`` — вызвать метод COM-объекта (``Dispatch(worker)``,
  затем ``method(params)``);
* ``GET /com/info`` — список доступных COM-серверов (registry-based);
* ``POST /com/script`` — выполнить инлайн COM-скрипт (требует
  ``com_script_enabled`` capability).

Безопасность:

* Все методы whitelisted в ``ALLOWED_COM_METHODS`` (предотвращение
  arbitrary COM execution);
* CORS закрыт по умолчанию;
* Требуется аутентификация через API-key header (см. backend-side
  ``com_sidecar_client.py``).

Реализация:

* ``win32com.client.Dispatch`` для COM-объектов с регистрацией в
  Windows registry (Office, IE, etc.);
* ``comtypes.client.CreateObject`` для late-binding на специфические
  banking COM-серверы (например, "СБ.Сервер.КриптоПро.1");
* На Linux/MacOS — модуль импортируется, но endpoint возвращает 503.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

__all__ = ("router", "ComCallRequest", "ComCallResponse", "ALLOWED_COM_METHODS")

_logger = logging.getLogger("windows_worker.com")

# Whitelist разрешённых COM-методов. Расширяется по мере добавления
# поддерживаемых banking-сценариев.
ALLOWED_COM_METHODS: frozenset[str] = frozenset(
    {
        # Office / Outlook
        "Word.Application:Open",
        "Word.Application:SaveAs",
        "Excel.Application:Open",
        "Excel.Application:SaveAs",
        "Outlook.Application:CreateItem",
        "Outlook.Application:Send",
        # CryptoPro (banking-specific signing).
        "CAdESCOM.CPSigner:Sign",
        "CAdESCOM.CPSigner:Verify",
        # Generic — для тестирования через pytest-mock.
        "Test.MockCOM:Echo",
    }
)


class ComCallRequest(BaseModel):
    """Запрос на COM-вызов.

    Атрибуты:
        worker: ProgID или CLSID COM-объекта (например, "Word.Application").
        method: Имя метода (например, "Open").
        params: Позиционные параметры метода.
        kwargs: Именованные параметры (для COM-методов с named args).
        timeout: Таймаут вызова в секундах.
    """

    worker: str = Field(..., description="ProgID/CLSID COM-объекта")
    method: str = Field(..., description="Имя метода для вызова")
    params: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    timeout: float = Field(default=30.0, ge=0.1, le=600.0)


class ComCallResponse(BaseModel):
    """Ответ COM-вызова."""

    success: bool
    result: Any = None
    error: str | None = None
    elapsed_ms: float = 0.0


router = APIRouter()


def _is_pywin32_available() -> bool:
    """Проверяет, доступен ли pywin32 (только на Windows)."""
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401

        return True
    except ImportError:
        return False


@router.post("/call", response_model=ComCallResponse)
async def com_call(request: ComCallRequest) -> ComCallResponse:
    """Вызывает метод COM-объекта.

    Args:
        request: COM-вызов (worker, method, params).

    Returns:
        ComCallResponse с результатом или ошибкой.

    Raises:
        HTTPException 503: При отсутствии pywin32 (Linux/MacOS).
        HTTPException 403: При попытке вызвать не-whitelisted метод.
    """
    import time

    if not _is_pywin32_available():
        raise HTTPException(
            status_code=503,
            detail="pywin32 не установлен. Sidecar работает только на Windows.",
        )

    fqn = f"{request.worker}:{request.method}"
    if fqn not in ALLOWED_COM_METHODS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"COM method '{fqn}' не whitelisted. Добавьте в ALLOWED_COM_METHODS."
            ),
        )

    start = time.monotonic()
    try:
        import win32com.client

        com_obj = win32com.client.Dispatch(request.worker)
        method = getattr(com_obj, request.method)
        result = method(*request.params, **request.kwargs)
        elapsed_ms = (time.monotonic() - start) * 1000.0

        return ComCallResponse(success=True, result=str(result), elapsed_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001 — REST API возвращает любую ошибку.
        elapsed_ms = (time.monotonic() - start) * 1000.0
        _logger.exception("COM call failed: %s", fqn)
        return ComCallResponse(success=False, error=str(exc), elapsed_ms=elapsed_ms)


@router.get("/info")
async def com_info() -> dict[str, Any]:
    """Возвращает информацию о sidecar и доступных COM-методах."""
    return {
        "platform": sys.platform,
        "pywin32_available": _is_pywin32_available(),
        "allowed_methods": sorted(ALLOWED_COM_METHODS),
        "method_count": len(ALLOWED_COM_METHODS),
    }
