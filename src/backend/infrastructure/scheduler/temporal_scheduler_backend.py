"""TemporalSchedulerBackend — real implementation via temporalio Schedule API.

**S105 W3 (replaces S18 W0 stub).**

Replaces the previous stub (S18 W0 scaffold, all methods threw
:class:`NotImplementedError`). Uses real ``temporalio.client.Client``:

* ``schedule_cron`` → ``client.create_schedule()`` с
  :class:`ScheduleActionStartWorkflow` + :class:`ScheduleCronSpec`.
* ``schedule_oneshot`` → ``client.start_workflow()`` с ``start_delay``.
* ``cancel`` → ``handle.delete()`` (для schedule) или
  ``handle.cancel()`` (для workflow).
* ``list_jobs`` → ``client.list_schedules()`` async iterator + history.

Semantic difference vs :class:`APSchedulerBackend` (важно!):

  APScheduler = "call this Python function at time T".
  Temporal = "start this Workflow at time T" (distributed, durable, retries).

Из-за этого ``callable_ref`` интерпретируется по-разному:

  * APScheduler: ``callable_ref`` = Python callable (sync или async function).
  * Temporal: ``callable_ref`` = string (workflow name, зарегистрированный в
    :class:`TemporalWorkerPool`) или tuple ``(workflow, args, kwargs)``.

Caller обязан адаптировать свои вызовы. Если ``callable_ref`` — не string/tuple,
бросает :class:`TypeError` с подсказкой.

Lazy import temporalio (~15-20MB). Если temporalio не установлен, бросает
:class:`ImportError` с инструкцией по установке. Это контрактно с другими
точками интеграции (``temporal_client.py``, ``temporal_backend.py``).

Out of scope (future):
* Schedule-to-Close retry policy: сейчас дефолтная. Custom policy = TBD.
* Workflow-level callback fallback: Temporal Activities могут быть
  использованы для sync Python work; сейчас backend ожидает workflows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = ("TemporalSchedulerBackend",)


class TemporalSchedulerBackend:
    """SchedulerBackend поверх temporalio Schedule API (real implementation).

    Args:
        client_factory: Опциональный :class:`TemporalClientFactory`. По
            умолчанию используется singleton из
            ``infrastructure.workflow.temporal_client``.
        namespace: Temporal namespace (default ``"default"``).
    """

    def __init__(
        self, client_factory: Any | None = None, *, namespace: str = "default"
    ) -> None:
        """Инициализация: lazy-bind к :class:`TemporalClientFactory`.

        Args:
            client_factory: Опциональная фабрика (для тестов).
            namespace: Temporal namespace.
        """
        if client_factory is None:
            from src.backend.infrastructure.workflow.temporal_client import (
                TemporalClientFactory,
            )

            client_factory = TemporalClientFactory()
        self._factory = client_factory
        self._namespace = namespace
        # In-memory cache имён для oneshot workflows (для list_jobs)
        self._oneshot_ids: dict[str, str] = {}  # name → workflow_id

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Запуск backend'а: warm-up connection (если ещё нет).

        Для Temporal нет отдельного "start" — client'ы создаются lazy
        при первом вызове. Этот метод — no-op для совместимости с
        :class:`APSchedulerBackend` API.
        """
        return None

    async def stop(self) -> None:
        """Остановка backend'а: cleanup.

        Тоже no-op: Temporal client lifecycle управляется через
        :class:`TemporalClientFactory.aclose` (явно из lifespan).
        """
        return None

    # ── schedule_cron ─────────────────────────────────────────────────

    def _validate_callable_ref(
        self, callable_ref: str | tuple[str, list[Any], dict[str, Any]]
    ) -> tuple[str, list[Any], dict[str, Any]]:
        """Валидация ``callable_ref`` (должен быть str или tuple).

        Args:
            callable_ref: ``str`` (workflow name) или
                ``tuple[str, list, dict]`` = ``(workflow, args, kwargs)``.

        Returns:
            ``(workflow, args, kwargs)`` tuple.

        Raises:
            TypeError: ``callable_ref`` — не str/tuple нужной формы.
        """
        if isinstance(callable_ref, str):
            return callable_ref, [], {}
        if (
            isinstance(callable_ref, tuple)
            and len(callable_ref) == 3
            and isinstance(callable_ref[0], str)
        ):
            workflow, args, kwargs = callable_ref
            if not isinstance(args, list):
                raise TypeError(
                    f"callable_ref[1] must be list, got {type(args).__name__}"
                )
            if not isinstance(kwargs, dict):
                raise TypeError(
                    f"callable_ref[2] must be dict, got {type(kwargs).__name__}"
                )
            return workflow, args, kwargs
        raise TypeError(
            "TemporalSchedulerBackend: callable_ref must be "
            "str (workflow name) or tuple[str, list, dict]. "
            "Got: " + repr(type(callable_ref).__name__)
        )

    async def schedule_cron(
        self,
        name: str,
        cron_expr: str,
        callable_ref: str | tuple[str, list[Any], dict[str, Any]],
        *,
        timezone: str = "Europe/Moscow",
        replace_existing: bool = True,
    ) -> str:
        """Создать Temporal Schedule с cron-триггером.

        Args:
            name: Уникальный ID schedule (Temporal Schedule ID).
            cron_expr: 5-field cron expression (e.g. ``"*/5 * * * *"``).
            callable_ref: ``str`` (workflow name) ИЛИ
                ``tuple[str, list, dict]`` = ``(workflow, args, kwargs)``.
                Temporal НЕ поддерживает arbitrary Python callables —
                caller обязан зарегистрировать workflow в WorkerPool.
            timezone: Cron timezone (e.g. ``"Europe/Moscow"``).
            replace_existing: Если True — пересоздать schedule с тем же ID.

        Returns:
            ``str`` — schedule_id (= name).

        Raises:
            TypeError: ``callable_ref`` — не str/tuple.
            ImportError: temporalio не установлен.
            RuntimeError: ошибка Temporal API.
        """
        # Валидация ДО импорта temporalio (быстрый fail на bad input).
        workflow, args, kwargs = self._validate_callable_ref(callable_ref)

        client = await self._factory.get_client(self._namespace)
        try:
            from temporalio.client import ScheduleActionStartWorkflow
        except ImportError as exc:
            raise ImportError(
                "temporalio не установлен. Установите: "
                "uv pip install 'temporalio>=1.27.0'"
            ) from exc

        # Если replace_existing — сначала удаляем старый schedule.
        if replace_existing:
            try:
                handle = client.get_schedule_handle(name)
                await handle.delete()
            except Exception:  # noqa: BLE001 — schedule мог не существовать
                pass

        # Cron parsing: 5 fields "minute hour day month day_of_week"
        spec = self._parse_cron_to_spec(cron_expr, timezone)

        await client.create_schedule(
            schedule_id=name,
            spec=spec,
            action=ScheduleActionStartWorkflow(
                workflow,
                *args,
                id=name,
                task_queue="default",  # caller может override через schedule meta
                **kwargs,
            ),
        )
        return name

    # ── schedule_oneshot ──────────────────────────────────────────────

    async def schedule_oneshot(
        self,
        name: str,
        run_at: datetime,
        callable_ref: str | tuple[str, list[Any], dict[str, Any]],
        *,
        replace_existing: bool = True,
    ) -> str:
        """Запустить workflow один раз в ``run_at``.

        Args:
            name: Workflow ID (используется как Temporal workflow ID).
            run_at: Когда запустить.
            callable_ref: str/tuple (см. :meth:`schedule_cron`).
            replace_existing: Для oneshot — no-op (Temporal не имеет
                "перезапуска" workflow; новый ID = новый workflow).

        Returns:
            ``str`` — workflow_id (= name).

        Raises:
            TypeError: ``callable_ref`` — не str/tuple.
            ImportError: temporalio не установлен.
        """
        # Валидация ДО импорта temporalio.
        workflow, args, kwargs = self._validate_callable_ref(callable_ref)

        client = await self._factory.get_client(self._namespace)

        # Temporal работает в UTC.
        if run_at.tzinfo is None:
            run_at_utc = run_at.replace(tzinfo=timezone.utc)
        else:
            run_at_utc = run_at.astimezone(timezone.utc)
        # start_delay — timedelta от now до run_at.
        now_utc = datetime.now(tz=timezone.utc)
        start_delay = max(run_at_utc - now_utc, timedelta(0))

        handle = await client.start_workflow(
            workflow,
            *args,
            id=name,
            task_queue="default",
            start_delay=start_delay,
            **kwargs,
        )
        self._oneshot_ids[name] = handle.id
        return handle.id

    # ── cancel ────────────────────────────────────────────────────────

    async def cancel(self, job_id: str) -> bool:
        """Удалить schedule (cron) или cancel workflow (oneshot).

        Args:
            job_id: Schedule ID или Workflow ID.

        Returns:
            ``True`` если успешно, ``False`` если не найдено / ошибка.

        Raises:
            ImportError: temporalio не установлен.
        """
        client = await self._factory.get_client(self._namespace)
        try:
            # Сначала пробуем как schedule (cron).
            try:
                handle = client.get_schedule_handle(job_id)
                await handle.delete()
                return True
            except Exception:  # noqa: BLE001
                # Не schedule — пробуем как workflow.
                wf_handle = client.get_workflow_handle(job_id)
                await wf_handle.cancel()
                self._oneshot_ids.pop(job_id, None)
                return True
        except Exception:  # noqa: BLE001
            return False

    # ── list_jobs ─────────────────────────────────────────────────────

    async def list_jobs(self) -> list[dict[str, Any]]:
        """Список активных schedules + недавно запущенных oneshot workflows.

        Returns:
            list of dicts с полями: ``id``, ``kind`` (``"cron"`` / ``"oneshot"``),
            ``workflow``, ``status``.

        Raises:
            ImportError: temporalio не установлен.
        """
        client = await self._factory.get_client(self._namespace)

        result: list[dict[str, Any]] = []

        # 1. Schedules (cron jobs).
        try:
            async for entry in client.list_schedules():
                # entry — ScheduleListEntry; поля: schedule_id, info (ScheduleListInfo).
                info = getattr(entry, "info", None)
                result.append(
                    {
                        "id": entry.schedule_id,
                        "kind": "cron",
                        "workflow": (info.workflow_type if info else "unknown"),
                        "status": "active",
                    }
                )
        except Exception:  # noqa: BLE001
            # list_schedules может не существовать в старых версиях.
            pass

        # 2. Oneshot workflows (из локального кэша — Temporal не имеет
        # "list oneshot workflows" API в чистом виде; workflows
        # отслеживаются через Temporal Visibility queries, что out of scope).
        for name, wf_id in self._oneshot_ids.items():
            result.append(
                {
                    "id": wf_id,
                    "kind": "oneshot",
                    "workflow": "unknown",  # не сохраняли workflow type
                    "status": "pending",
                }
            )

        return result

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_cron_to_spec(cron_expr: str, tz: str) -> Any:
        """Парсит 5-field cron в :class:`ScheduleCronSpec`.

        Args:
            cron_expr: 5-field cron ``"minute hour day month day_of_week"``.
            tz: Cron timezone.

        Returns:
            :class:`ScheduleCronSpec` instance.

        Raises:
            ImportError: temporalio не установлен.
            ValueError: invalid cron expression.
        """
        try:
            from temporalio.client import ScheduleCronSpec
        except ImportError as exc:
            raise ImportError(
                "temporalio не установлен. Установите: "
                "uv pip install 'temporalio>=1.27.0'"
            ) from exc

        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(
                f"cron_expr должен быть 5-field: minute hour day month day_of_week. "
                f"Got: {cron_expr!r}"
            )
        minute, hour, day, month, day_of_week = parts
        return ScheduleCronSpec(
            minute=minute,
            hour=hour,
            day_of_month=day,
            month=month,
            day_of_week=day_of_week,
            timezone=tz,
        )
