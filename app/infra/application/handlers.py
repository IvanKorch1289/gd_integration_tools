from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.utils.logging_service import app_logger


__all__ = ("setup_handlers",)


def setup_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        error_id = request.state.request_id
        error_message = f"Error [{error_id}]: {str(exc)}"

        app_logger.error(error_message, exc_info=True)

        return JSONResponse(
            status_code=getattr(exc, "status_code", 500),
            content={
                "error": {
                    "id": error_id,
                    "code": getattr(exc, "code", "internal_error"),
                    "message": str(exc),
                }
            },
        )
