from app.services.route_services.orders import get_order_service
from app.utils.logging_service import queue_logger


__all__ = ("process_order",)


async def process_order(payload: dict):
    """Обработчик заказов"""
    queue_logger.info(f"Processing message. Payload: {payload}")
    try:
        order_service = get_order_service()

        await order_service.add(data=payload)
    except Exception:
        queue_logger.error(
            f"Error processing message. Payload: {payload}", exc_info=True
        )
