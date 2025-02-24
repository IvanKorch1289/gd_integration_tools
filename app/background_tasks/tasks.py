from datetime import datetime, timedelta

from taskiq.exceptions import NoResultError
from taskiq_pipelines import Pipeline

from app.background_tasks.worker import broker
from app.config.settings import settings
from app.grpc.grpc_client import grpc_client
from app.utils.logging_service import tasks_logger


__all__ = (
    "send_mail_task",
    "create_skb_order_task",
    "get_skb_order_result_task",
    "skb_order_pipeline",
)


RETRY_POLICY = {
    "max_retries": settings.tasks.max_attempts,  # Максимальное количество попыток
    "delay": settings.tasks.seconds_delay,  # Задержка между попытками в секундах
}


@broker.task(retry=RETRY_POLICY)
async def send_mail_task(body: dict) -> dict:
    from app.services.infra_services.mail import get_mail_service

    async with get_mail_service() as mail_service:
        return await mail_service.send_email(
            to_emails=body["to_emails"],
            subject=body["subject"],
            message=body["message"],
        )


@broker.task(retry=RETRY_POLICY)
async def create_skb_order_task(body: dict) -> dict:
    """Taskiq task for order creation"""
    try:
        result = await grpc_client.create_order(order_id=body["id"])

        if int(result.get("status")) != 200:
            raise NoResultError("SKB order creation failed")

        return {
            **result,
            "notification_emails": body.get("email_for_answer", []),
            "id": body["id"],
        }
    except Exception as exc:
        tasks_logger.error("Create order error", exc_info=True)
        # Возвращаем флаг ошибки и информацию для отправки письма
        return {
            "error": True,
            "message": str(exc),
            "notification_emails": body.get("email_for_answer", []),
            "id": body["id"],
        }


@broker.task(retry=RETRY_POLICY)
async def get_skb_order_result_task(body: dict) -> dict:
    """
    Задача для получения результата с повторными попытками.
    """
    try:
        """Taskiq task for result fetching"""
        result = await grpc_client.get_order_result(
            order_id=body["id"], skb_id=body["object_uuid"]
        )

        # Кастомная проверка результата
        if int(result.get("status")) != 200:
            raise NoResultError("Order result not ready")

        return {
            "final_result": result,
            "notification_emails": body["email_for_answer"],
            "original_id": body["id"],
        }
    except Exception as exc:
        tasks_logger.error("Get result error", exc_info=True)
        # Возвращаем флаг ошибки и информацию для отправки письма
        return {
            "error": True,
            "message": str(exc),
            "notification_emails": body["email_for_answer"],
            "original_id": body["id"],
        }


def _check_error_and_continue(result: dict, next_step: callable) -> dict:
    """Проверяет наличие ошибки и решает, продолжать ли пайплайн."""
    if result.get("error"):
        # Если есть ошибка, завершаем пайплайн отправкой письма
        return {
            "notification_emails": result["notification_emails"],
            "message": result["message"],
            "error": True,
        }
    # Если ошибки нет, продолжаем пайплайн
    return next_step(result)


skb_order_pipeline = (
    Pipeline(broker, create_skb_order_task)
    # Успешное создание -> запуск получения результата через 30 мин
    .call_next(
        get_skb_order_result_task,
        eta=datetime.now() + timedelta(minutes=30),
        transform=lambda result, args: _check_error_and_continue(
            result,
            lambda res: {
                "object_uuid": res["object_uuid"],
                "notification_emails": res["notification_emails"],
                "original_id": res["original_id"],
            },
        ),
    )
    # Финализация: отправка письма
    .call_next(
        send_mail_task,
        transform=lambda result, args: {
            "notification_emails": result["notification_emails"],
            "message": result.get("message", "Нет дополнительной информации"),
            "error": result.get("error", False),
        },
    )
)
