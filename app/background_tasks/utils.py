from asyncio import sleep
from datetime import datetime, timedelta

from prefect import get_client
from prefect.context import get_run_context
from prefect.states import Paused

from app.infra.scheduler.scheduler_manager import scheduler_manager
from app.utils.logging_service import tasks_logger


__all__ = ("managed_pause",)


async def scheduled_resume_flow_run(flow_run_id: str):
    """
    Функция, которая будет вызвана планировщиком для возобновления flow run.
    """
    try:
        async with get_client() as client:
            # Возобновляем flow run
            await client.resume_flow_run(flow_run_id)
            tasks_logger.info(f"Flow run {flow_run_id} resumed successfully")
    except Exception as exc:
        tasks_logger.error(
            f"Failed to resume flow run {flow_run_id}: {str(exc)}"
        )
        raise


async def managed_pause(delay_seconds: int):
    """
    Приостанавливает текущий flow run и планирует его возобновление через указанное время.
    """
    # Получаем контекст выполнения
    ctx = get_run_context()
    flow_run_id = ctx.flow_run.id
    # Создаем планировщик
    scheduler = scheduler_manager.scheduler

    try:
        # Планируем возобновление через указанное время
        scheduler.add_job(
            scheduled_resume_flow_run,
            "date",
            run_date=datetime.now() + timedelta(seconds=delay_seconds),
            args=[flow_run_id],
            id=f"resume_{flow_run_id}",
        )
        # Приостанавливаем flow run
        async with get_client() as client:
            await client.set_flow_run_state(
                flow_run_id=flow_run_id, state=Paused(), force=True
            )
        tasks_logger.info(f"Flow run {flow_run_id} paused successfully")
        # Ждем, чтобы убедиться, что flow run приостановлен
        await sleep(delay_seconds)

    except Exception as exc:
        tasks_logger.error(f"Error in managed_pause: {str(exc)}")
        raise
