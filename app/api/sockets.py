from fastapi import APIRouter, WebSocket

from app.config.settings import settings
from app.utils.logging_service import request_logger


__all__ = ("router",)


router = APIRouter()


@router.websocket("/ws/settings")
async def websocket_settings(websocket: WebSocket):
    """
    WebSocket endpoint to send application settings.
    """
    await websocket.accept()
    try:
        # Send settings in JSON format
        await websocket.send_text(settings.model_dump_json())
        await websocket.close()
    except Exception:
        request_logger.critical("WebSocket error", exc_info=True)
        await websocket.close(code=1011)
