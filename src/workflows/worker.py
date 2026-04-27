"""Standalone durable workflow worker (IL-WF1.4).

Отдельный docker-процесс, который крутит
:class:`app.infrastructure.workflow.runner.DurableWorkflowRunner` и выполняет
pending workflow instances. Реплики worker-а координируются через advisory-lock
+ DB-lease (см. ``state_store.try_lock``), поэтому можно запускать сколько угодно
pod-ов параллельно — каждый pending-инстанс будет подхвачен ровно одним.

CLI (Typer), стиль совпадает с ``manage.py``::

    # local dev (PYTHONPATH=src):
    python -m workflows.worker run [--worker-id ...] [--max-concurrent 8]
    # docker image (PYTHONPATH=/app, src копируется в /app/app):
    python -m app.workflows.worker run ...
    python -m app.workflows.worker status
    python -m app.workflows.worker drain

Команды:

* ``run`` — forever loop до SIGTERM/SIGINT. Поднимает runner + K8s-probes
  HTTP-сервер; graceful shutdown ждёт завершения активных executions (или
  ``SHUTDOWN_GRACE_SECONDS``).
* ``status`` — одноразовый запрос БД: количество инстансов по статусам.
* ``drain`` — помечает локальный runtime-файл как draining. В текущей
  реализации печатает hint как drain-ить работающий pod через K8s (SIGTERM
  handler включает drain автоматически).

Wave 3.2 / IL-WF1.3: runner выполняет шаги через :class:`DSLStepExecutor`,
который загружает :class:`WorkflowSpec` из :data:`workflow_registry` по
``instance.route_id``. Hot-reload spec работает «из коробки» —
``spec_loader`` пересматривает реестр на каждом шаге.

Legacy :class:`NoOpStepExecutor` оставлен как dev-only fallback и
активируется переменной ``WORKFLOW_WORKER_EXECUTOR=noop`` (для smoke-проверок
lifecycle без реальных spec'ов).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import typer

__all__ = ("app", "NoOpStepExecutor", "main", "build_spec_loader")

_logger = logging.getLogger("workflow.worker")

app = typer.Typer(
    name="workflow-worker",
    help="Durable workflow worker — выполняет pending instances.",
    add_completion=False,
)


# ── Executors: prod (DSL) + dev-only (NoOp) ──────────────────────────


def build_spec_loader() -> Callable[[str], Any]:
    """Фабрика ``SpecLoader`` для :class:`DSLStepExecutor`.

    Spec ищется в :data:`workflow_registry`. ``KeyError`` (unknown route_id)
    конвертируется executor'ом в ``StepOutcome.FAILED`` — runner увидит
    событие ``step_failed`` с причиной ``spec_not_found``.
    """
    from src.workflows.registry import workflow_registry

    def _loader(route_id: str) -> Any:
        spec = workflow_registry.get_spec(route_id)
        if spec is None:
            raise KeyError(route_id)
        return spec

    return _loader


def _resolve_executor() -> Any:
    """Выбирает step-executor по переменной ``WORKFLOW_WORKER_EXECUTOR``.

    По умолчанию — DSL executor (prod path). Значение ``noop`` — fallback
    для smoke-lifecycle-проверок без spec'ов.
    """
    mode = os.environ.get("WORKFLOW_WORKER_EXECUTOR", "dsl").lower()
    if mode == "noop":
        _logger.warning(
            "WORKFLOW_WORKER_EXECUTOR=noop — NoOpStepExecutor active (dev/smoke)"
        )
        return NoOpStepExecutor()
    from src.infrastructure.workflow.executor import DSLStepExecutor

    return DSLStepExecutor(spec_loader=build_spec_loader())


class NoOpStepExecutor:
    """Dev-only step executor (smoke-lifecycle без spec'ов).

    Логирует факт вызова и возвращает ``StepResult(outcome=DONE, events=[])``.
    Нужен только чтобы проверить lifecycle worker-а (lock → replay →
    execute → record → unlock) в окружениях без регистрированных workflow
    spec-ов. В prod-пути замещён :class:`DSLStepExecutor` — активация
    через ``WORKFLOW_WORKER_EXECUTOR=noop``.
    """

    async def execute_next(
        self,
        *,
        instance: Any,
        state: Any,  # noqa: ARG002
    ) -> Any:
        # Импорт отложен чтобы CLI --help не тянул БД/модели.
        from src.infrastructure.workflow.runner import StepOutcome, StepResult

        _logger.warning(
            "NoOpStepExecutor.execute_next called for workflow %s — "
            "returning DONE (dev-only fallback)",
            getattr(instance, "id", "<unknown>"),
        )
        return StepResult(outcome=StepOutcome.DONE, events=[], output_state=None)


# ── Lifecycle helpers ─────────────────────────────────────────────────


@dataclass(slots=True)
class _WorkerContext:
    """Агрегат live-объектов, нужный для graceful-shutdown."""

    runner: Any
    probes: Any
    shutdown_event: asyncio.Event


async def _bootstrap() -> None:
    """Минимальная инициализация: сервисы + БД + коннекторы.

    Аналогично ``manage.py._bootstrap``, но дополнительно стартует
    ``ConnectorRegistry`` — worker-у нужны живые БД-подключения.
    """
    from src.dsl.commands.setup import register_action_handlers
    from src.dsl.routes import register_dsl_routes
    from src.infrastructure.application.service_setup import register_all_services

    register_all_services()
    register_action_handlers()
    register_dsl_routes()

    # Коннекторы (БД + внешние клиенты) — если registry доступен.
    try:
        from src.infrastructure.registry import ConnectorRegistry

        await ConnectorRegistry.instance().start_all()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("ConnectorRegistry.start_all failed (продолжаем): %s", exc)


async def _shutdown_connectors() -> None:
    """Останавливает коннекторы в обратном порядке. Ошибки не фатальны."""
    try:
        from src.infrastructure.registry import ConnectorRegistry

        await ConnectorRegistry.instance().stop_all()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("ConnectorRegistry.stop_all failed: %s", exc)


async def _readiness_check() -> bool:
    """Проверка готовности для /readyz.

    Выполняет лёгкий ``SELECT 1`` через main_session_manager, чтобы
    убедиться что БД отвечает. Возвращает ``False`` при любой ошибке.
    """
    try:
        from sqlalchemy import text

        from src.infrastructure.database.session_manager import main_session_manager

        async with main_session_manager.create_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        _logger.debug("readiness check failed: %s", exc)
        return False


def _resolve_listener_dsn() -> str | None:
    """Возвращает plain asyncpg-DSN (для LISTEN/NOTIFY) из Settings.

    ``async_connection_url`` у ``DatabaseConnectionSettings`` имеет префикс
    ``postgresql+asyncpg://`` (SQLAlchemy-style); для ``asyncpg.connect``
    нужен чистый ``postgresql://``. Переводим.
    """
    try:
        from src.core.config.settings import settings

        url = str(settings.database.async_connection_url)
        if url.startswith("postgresql+asyncpg://"):
            return "postgresql://" + url[len("postgresql+asyncpg://") :]
        if url.startswith("postgresql+psycopg://"):
            return "postgresql://" + url[len("postgresql+psycopg://") :]
        return url
    except Exception as exc:  # noqa: BLE001
        _logger.warning("cannot resolve listener DSN: %s", exc)
        return None


async def _run_worker(
    *, worker_id: str, max_concurrent: int, listen: bool, probes_port: int
) -> None:
    """Внутренний async-entrypoint команды ``run``.

    Делает bootstrap, создаёт runner + probes, регистрирует signal-handler'ы
    и ждёт shutdown event. По shutdown — graceful drain: probes → 503,
    runner.stop() ждёт завершения активных executions, probes.stop().
    """
    from src.infrastructure.workflow.runner import DurableWorkflowRunner, RunnerConfig
    from src.workflows.worker_probes import WorkerProbesServer

    await _bootstrap()

    config = RunnerConfig(worker_id=worker_id, max_concurrent=max_concurrent)
    listener_dsn = _resolve_listener_dsn() if listen else None

    runner = DurableWorkflowRunner(
        config=config, executor=_resolve_executor(), listener_dsn=listener_dsn
    )

    probes = WorkerProbesServer(
        runner=runner,
        worker_id=worker_id,
        port=probes_port,
        readiness_check=_readiness_check,
    )

    shutdown_event = asyncio.Event()

    # SIGTERM/SIGINT handlers — событие для graceful drain.
    loop = asyncio.get_running_loop()

    def _on_signal(sig: signal.Signals) -> None:
        _logger.info("received %s — initiating graceful shutdown", sig.name)
        probes.mark_draining()
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
        except NotImplementedError:
            # Windows или не-main thread — signal handlers недоступны,
            # остаётся только KeyboardInterrupt.
            pass

    _logger.info(
        "starting worker (id=%s, max_concurrent=%d, listen=%s, probes_port=%d)",
        worker_id,
        max_concurrent,
        listen,
        probes_port,
    )

    grace_seconds = int(os.environ.get("SHUTDOWN_GRACE_SECONDS", "30"))

    try:
        await probes.start()
        await runner.start()
        await shutdown_event.wait()
    finally:
        _logger.info("stopping runner (grace=%ds)...", grace_seconds)
        try:
            await asyncio.wait_for(runner.stop(), timeout=grace_seconds)
        except asyncio.TimeoutError:
            _logger.warning("runner.stop() timed out after %ds", grace_seconds)
        except Exception as exc:  # noqa: BLE001
            _logger.error("runner.stop() error: %s", exc)
        try:
            await probes.stop()
        except Exception as exc:  # noqa: BLE001
            _logger.error("probes.stop() error: %s", exc)
        await _shutdown_connectors()
        _logger.info("worker shutdown complete")


async def _print_status() -> None:
    """Async-helper команды ``status``: печатает счётчики по статусам."""
    from sqlalchemy import func, select

    from src.infrastructure.database.models.workflow_instance import (
        WorkflowInstance,
        WorkflowStatus,
    )
    from src.infrastructure.database.session_manager import main_session_manager

    await _bootstrap()
    async with main_session_manager.create_session() as session:
        stmt = select(
            WorkflowInstance.status, func.count(WorkflowInstance.id)
        ).group_by(WorkflowInstance.status)
        result = await session.execute(stmt)
        rows = result.all()

    if not rows:
        typer.echo("(no workflow instances)")
        return

    typer.echo(f"Workflow instances ({datetime.utcnow().isoformat()}Z):")
    total = 0
    for status, count in rows:
        total += int(count)
        name = status.name if isinstance(status, WorkflowStatus) else str(status)
        typer.echo(f"  {name:<12} {count}")
    typer.echo(f"  {'total':<12} {total}")


# ── Typer команды ─────────────────────────────────────────────────────


@app.command()
def run(
    worker_id: str = typer.Option(
        None,
        "--worker-id",
        help="Override worker_id (default: env WORKFLOW_WORKER_ID или worker-<rand>).",
    ),
    max_concurrent: int = typer.Option(
        8, "--max-concurrent", help="Max параллельно выполняемых инстансов."
    ),
    listen: bool = typer.Option(
        True,
        "--listen/--no-listen",
        help="Включить pg_notify LISTEN (push-path). Backup-polling работает всегда.",
    ),
    probes_port: int = typer.Option(
        9100, "--probes-port", help="Порт HTTP-сервера K8s probes + /metrics."
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Python logging level."),
):
    """Запускает worker forever до SIGTERM/SIGINT."""
    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    resolved_worker_id = (
        worker_id
        or os.environ.get("WORKFLOW_WORKER_ID")
        or f"worker-{uuid.uuid4().hex[:8]}"
    )
    try:
        asyncio.run(
            _run_worker(
                worker_id=resolved_worker_id,
                max_concurrent=max_concurrent,
                listen=listen,
                probes_port=probes_port,
            )
        )
    except KeyboardInterrupt:
        typer.echo("Interrupted.")


@app.command()
def status():
    """Печатает распределение инстансов по статусам (быстрый snapshot из БД)."""
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(_print_status())
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"status error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def drain():
    """Инициирует graceful drain запущенного worker-а.

    В текущей реализации worker реагирует на SIGTERM/SIGINT — эта команда
    лишь печатает подсказку как это сделать в K8s / docker-compose. Команда
    оставлена как entry-point для будущей интеграции с admin API.
    """
    typer.echo(
        "Чтобы graceful drain running worker — отправьте SIGTERM его процессу:\n"
        "  kubectl delete pod <worker-pod>            # K8s делает это автоматически\n"
        "  docker compose stop workflow-worker        # docker-compose\n"
        "  kill -TERM <pid>                           # bare metal\n"
        "\n"
        "Worker пометит /readyz как 503, дождётся завершения активных executions\n"
        "(до SHUTDOWN_GRACE_SECONDS, default 30s) и выйдет."
    )


def main() -> None:
    """Console-script entry-point: ``python -m src.workflows.worker``."""
    app()


if __name__ == "__main__":
    main()
    sys.exit(0)
