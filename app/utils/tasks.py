from taskiq_pipelines import Pipeline

from app.config.constants import RETRY_POLICY
from app.main import broker
from app.services.infra_services.mail import get_mail_service
from app.services.route_services.orders import get_order_service
from app.utils.logging_service import tasks_logger


__all__ = (
    "send_mail_task",
    "create_skb_order_task",
    "get_skb_order_result_task",
    "skb_order_pipeline",
)


@broker.task(retry=RETRY_POLICY)
async def send_mail_task(body: dict) -> dict:
    async with get_mail_service() as mail_service:
        return await mail_service.send_email(
            to_emails=body["to_emails"],
            subject=body["subject"],
            message=body["message"],
        )


@broker.task(retry=RETRY_POLICY)
async def create_skb_order_task(ctx: dict) -> dict:
    """
    Задача для создания заказа в SKB с повторными попытками.
    """
    try:
        order_id = ctx["order_id"]

        result = await get_order_service().create_skb_order(order_id=order_id)

        if not result.get("data", {}).get("Result"):
            raise RuntimeError("SKB order creation failed")

        return {"order_id": order_id, "initial_result": result}
    except Exception:
        tasks_logger.error("Error during SKB order creation", exc_info=True)
        raise


@broker.task(retry=RETRY_POLICY)
async def get_skb_order_result_task(ctx: dict) -> dict:
    """
    Задача для получения результата с повторными попытками.
    """
    try:
        order_id = ctx["order_id"]

        result = await get_order_service().get_order_result(order_id=order_id)

        # Кастомная проверка результата
        if result.get("status") != "completed":
            raise ValueError("Order result not ready")

        return {"final_result": result}
    except Exception:
        tasks_logger.error(
            "Error during SKB order result retrieval", exc_info=True
        )
        raise


# Создаем пайплайн
skb_order_pipeline = (
    Pipeline(broker)
    .call_next(create_skb_order_task)
    .call_next(get_skb_order_result_task)
)
