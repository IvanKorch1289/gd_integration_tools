from prefect import task

from app.background_tasks.dicts import ProcessingResult
from app.config.settings import settings
from app.services.route_services.orders import get_order_service
from app.utils.logging_service import tasks_logger


__all__ = (
    "send_notification_task",
    "create_skb_order_task",
    "get_skb_order_result_task",
)


@task(
    name="send-notification",
    description="Send email message to the specified address",
    retries=settings.tasks.task_max_attempts,
    retry_delay_seconds=settings.tasks.task_seconds_delay,
    retry_jitter_factor=settings.tasks.task_retry_jitter_factor,
    timeout_seconds=600,
    persist_result=True,
)
async def send_notification_task(body: dict) -> dict:
    from app.services.infra_services.mail import get_mail_service

    async with get_mail_service() as mail_service:
        return await mail_service.send_email(
            to_emails=body["to_emails"],
            subject=body["subject"],
            message=body["message"],
        )


@task(
    name="create-skb-order",
    description="Creates order in SKB system with retry logic",
    retries=settings.tasks.task_max_attempts,
    retry_delay_seconds=settings.tasks.task_seconds_delay,
    retry_jitter_factor=settings.tasks.task_retry_jitter_factor,
    timeout_seconds=3600,
    persist_result=True,
)
async def create_skb_order_task(order_data: dict) -> ProcessingResult:
    """
    Creates a new order in the SKB system with validation and retries.

    Args:
        order_data: Input order data

    Returns:
        ProcessingResult with creation status

    Raises:
        ValueError: For invalid input data
        ConnectionError: For communication failures
    """
    # Validate input
    if not order_data.get("id"):
        raise ValueError("Missing required order_id")

    try:
        result = await get_order_service().create_skb_order(
            order_id=order_data["id"]
        )

        if result.get("response", {}).get("status_code", {}) != 200:
            raise Exception("SKB order creation failed")

        return {
            "success": True,
            "order_id": order_data["id"],
            "result_data": {},
            "error_message": None,
        }
    except Exception as exc:
        tasks_logger.error("Create order error", exc_info=True)
        return {
            "success": False,
            "order_id": order_data["id"],
            "result_data": {},
            "error_message": str(exc),
        }


@task(
    name="get-skb-order-result",
    description="Get order's result in SKB system with retry logic",
    retries=settings.tasks.task_max_attempts,
    retry_delay_seconds=settings.tasks.task_seconds_delay,
    retry_jitter_factor=settings.tasks.task_retry_jitter_factor,
    timeout_seconds=86400,
    persist_result=True,
)
async def get_skb_order_result_task(order_data: dict) -> ProcessingResult:
    """
    Gets order's result in the SKB system with validation and retries.

    Args:
        order_data: Input order data

    Returns:
        ProcessingResult with result status

    Raises:
        ValueError: For invalid input data
        ConnectionError: For communication failures
    """
    # Validate input
    if not order_data.get("id"):
        raise ValueError("Missing required order_id")

    try:
        result = await get_order_service().get_order_file_and_json_from_skb(
            order_id=order_data["id"]
        )

        if result.get("response", {}).get("status_code", {}) != 200:
            raise Exception("SKB order creation failed")

        return {
            "success": True,
            "order_id": order_data["id"],
            "result_data": result,
            "error_message": None,
        }
    except Exception as exc:
        tasks_logger.error("Get result error", exc_info=True)
        return {
            "success": False,
            "order_id": order_data["id"],
            "result_data": {},
            "error_message": str(exc),
        }
