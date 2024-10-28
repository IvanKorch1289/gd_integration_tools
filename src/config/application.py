import asyncio
from functools import partial
from typing import Callable, Coroutine, Iterable

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from src.infrastructure.errors import (
    BaseError,
    custom_base_errors_handler,
    pydantic_validation_errors_handler,
    python_base_error_handler,
)

__all__ = ("create",)


def create(
    *_,
    rest_routers: Iterable[APIRouter],
    startup_tasks: Iterable[Callable[[], Coroutine]] | None = None,
    shutdown_tasks: Iterable[Callable[[], Coroutine]] | None = None,
    **kwargs,
) -> FastAPI:
    app = FastAPI(**kwargs)

    for router in rest_routers:
        app.include_router(router)

    app.exception_handler(RequestValidationError)(
        pydantic_validation_errors_handler
    )
    app.exception_handler(BaseError)(custom_base_errors_handler)
    app.exception_handler(ValidationError)(pydantic_validation_errors_handler)
    app.exception_handler(Exception)(python_base_error_handler)

    if startup_tasks:
        for task in startup_tasks:
            coro = partial(asyncio.create_task, task())
            app.on_event("startup")(coro)

    if shutdown_tasks:
        for task in shutdown_tasks:
            app.on_event("shutdown")(task)

    return app
