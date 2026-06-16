"""S111 W2 — FastAPI lifespan orchestrator (slim).

Refactored from 718 LOC god-context-manager into per-phase handlers:

* :mod:`src.backend.plugins.composition.lifecycle.startup` — startup phase
  (TaskRegistry, OTel, Sentry, services, plugins, etc.)
* :mod:`src.backend.plugins.composition.lifecycle.shutdown` — shutdown phase
  (workflow, plugins, sinks, TaskRegistry cancel, etc.)
* :mod:`src.backend.plugins.composition.lifecycle.signals` — SIGTERM/SIGINT
  graceful shutdown handlers

``lifespan()`` is now a thin orchestrator: install signals → run startup →
yield → run shutdown.

**Backward compatibility:** ``_register_outbox_dispatcher()`` (S64 W3 cutover)
was moved to :mod:`startup` but is re-exported here so existing imports
(``from .lifespan import _register_outbox_dispatcher``) and the test
``tests/unit/plugins/composition/lifecycle/test_outbox_dispatcher_cutover.py``
keep working unchanged.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry

if TYPE_CHECKING:
    pass

# Re-export for backward compat (S64 W3 cutover test references this).
from src.backend.plugins.composition.lifecycle.startup import (  # noqa: E402,F401
    _register_outbox_dispatcher,
)

app_logger = get_logger("application")

__all__ = ("lifespan", "_register_outbox_dispatcher")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: signal install → startup → yield → shutdown.

    Slim wrapper around per-phase handlers in :mod:`startup` /
    :mod:`shutdown` / :mod:`signals`. Preserves all original semantics:

    * TaskRegistry singleton инициализируется ДО try (R-V15-11).
    * Startup errors propagate (FastAPI reports as startup failure).
    * Shutdown errors are caught and logged by individual subsystems
      (best-effort, never blocks other subsystems).
    * TaskRegistry.shutdown_all() is called LAST in shutdown, AFTER
      all subsystems have had a chance to log their teardown.
    """
    app_logger.info("Запуск приложения...")

    # Sprint 1 V16 (R-V15-11): TaskRegistry singleton — все asyncio.create_task
    # в проекте проходят через него для graceful shutdown и correlation_id
    # propagation. Выносится ДО try, чтобы finally-блок мог корректно вызвать
    # shutdown_all даже при падении в startup.
    task_registry = get_task_registry()
    app.state.task_registry = task_registry

    # Install SIGTERM/SIGINT handlers (graceful shutdown hook).
    # No-op в test env (PYTEST_CURRENT_TEST set).
    from src.backend.plugins.composition.lifecycle.signals import (
        install_signal_handlers,
    )

    install_signal_handlers()

    # Lazy import of run_startup to defer composition-package import-bugs
    # (see test_outbox_dispatcher_cutover.py for stubbing strategy).
    from src.backend.plugins.composition.lifecycle.shutdown import run_shutdown
    from src.backend.plugins.composition.lifecycle.startup import run_startup

    startup_completed = False
    try:
        await run_startup(app, task_registry)
        startup_completed = True
        app.state.infrastructure_ready = True
        app_logger.info("Приложение успешно запущено")
        yield
    except Exception as exc:
        if not startup_completed:
            app_logger.critical(
                "Критическая ошибка при запуске приложения: %s", str(exc), exc_info=True
            )
            raise RuntimeError(
                "Остановка приложения из-за ошибки инициализации"
            ) from exc

        app_logger.critical(
            "Критическая ошибка во время работы приложения: %s", str(exc), exc_info=True
        )
        raise
    finally:
        if startup_completed:
            app_logger.info("Завершение работы приложения...")
            await run_shutdown(app, task_registry)
