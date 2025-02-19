from taskiq.exceptions import NoResultError
from taskiq_pipelines import Pipeline

from app.background_tasks.worker import broker
from app.config.settings import settings
from app.grpc.grpc_client import grpc_client
from app.services.infra_services.mail import get_mail_service
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
async def create_skb_order_task(order_id: int) -> dict:
    """Taskiq task for order creation"""
    try:
        # result = await get_order_service().create_skb_order(order_id=order_id)
        result = await grpc_client.create_order(order_id)

        if not result.get("data", {}).get("Result"):
            raise RuntimeError("SKB order creation failed")

        return {
            "order_id": order_id,
            "status": "created",
        }
    except Exception as exc:
        # Добавляем информацию о попытках в контекст
        current_retry = getattr(create_skb_order_task.task, "current_retry", 0)
        if current_retry >= RETRY_POLICY["max_retries"] - 1:
            tasks_logger.error(f"Final attempt failed for order {order_id}")
            raise NoResultError(
                message=str(exc), retry_type="max_retries_exceeded"
            )
        raise


@broker.task(retry=RETRY_POLICY)
async def handle_failure(ctx: dict) -> dict:
    """Обработчик неудачных попыток создания заказа."""
    try:
        async with get_mail_service() as mail_service:
            await mail_service.send_email(
                to_emails=ctx["user_email"],
                subject="Order Creation Failed",
                message=f"Failed to create order {ctx['order_id']} after {RETRY_POLICY["max_retries"]} attempts",
            )
        return {"status": "failed", "error": ctx.get("error")}
    except Exception:
        tasks_logger.error(
            "Failed to send failure notification", exc_info=True
        )
        raise


@broker.task(retry=RETRY_POLICY)
async def get_skb_order_result_task(ctx: dict) -> dict:
    """
    Задача для получения результата с повторными попытками.
    """
    try:
        """Taskiq task for result fetching"""
        result = await grpc_client.get_order_result(
            ctx["order_id"], ctx["skb_id"]
        )

        # result = await get_order_service().get_order_result(order_id=ctx["order_id"])

        # Кастомная проверка результата
        if result.get("status") != "completed":
            raise ValueError("Order result not ready")

        return {"final_result": result}
    except Exception:
        tasks_logger.error(
            "Error during SKB order result retrieval", exc_info=True
        )
        raise


def conditional_next(result: dict):
    """Функция ветвления на основе результата."""
    if result.get("status") == "created":
        return get_skb_order_result_task
    return handle_failure


# # Модифицированный пайплайн с ветвлением
# skb_order_pipeline = (
#     Pipeline(broker, create_skb_order_task)
#     .call_next(
#         conditional_next,
#         # Передаем аргументы для обработки ошибок
#         error_handler_args=lambda prev_result: {
#             "order_id": prev_result["order_id"]
#         },
#     )
#     .call_next(send_mail_task)
# )
