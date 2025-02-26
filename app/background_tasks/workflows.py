from typing import Any, Dict

from prefect import flow, pause_flow_run

from app.background_tasks.tasks import (
    create_skb_order_task,
    get_skb_order_result_task,
    send_notification_task,
)
from app.config.settings import settings


__all__ = (
    "get_skb_order_result_workflow",
    "send_notification_workflow",
    "create_skb_order_workflow",
    "order_processing_workflow",
)


@flow(
    name="send-notification-workflow",
    description="Sends a mail to a customer using the specified email address",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    timeout_seconds=settings.tasks.flow_timeout_seconds,  # 24 hours
    persist_result=True,
)
async def send_notification_workflow(body: dict):
    """
    Sends a mail to a customer with exponential backoff

    Args:
        body: Email data
    Returns:
        None
    """
    await send_notification_task(body)


@flow(
    name="create-skb-order-workflow",
    description="Creates a new order workflow for a customer with a given order number",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    timeout_seconds=settings.tasks.flow_timeout_seconds,  # 24 hours
    persist_result=True,
)
async def create_skb_order_workflow(body: dict):
    """
    Creates a new order in the SKB system with exponential backoff

    Args:
        body: Order data
    Returns:
        Processing result
    """
    await create_skb_order_task(body)


@flow(
    name="get-skb-order-result-task-workflow",
    description="Retrieves the result task for a given skb order",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    timeout_seconds=settings.tasks.flow_timeout_seconds,  # 24 hours
    persist_result=True,
)
async def get_skb_order_result_workflow(body: dict):
    """
    Retrieves the result task for a given skb order with exponential backoff

    Args:
        body: Order data

    Returns:
        Processing result
    """
    await get_skb_order_result_task(body)


@flow(
    name="order-processing-workflow",
    description="Simplified order processing with retries and error handling",
    retries=settings.tasks.flow_max_attempts,
    retry_delay_seconds=settings.tasks.flow_seconds_delay,
    timeout_seconds=86400,  # 24 hours
)
async def order_processing_workflow(
    order_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Simplified order processing flow with core functionality:
    1. Order creation with retries
    2. Initial delay before first check
    3. Result polling with backoff
    4. Error handling and notifications

    Args:
        order_data: Dictionary with order parameters:
            - id: Order identifier (required)
            - notification_emails: List of emails for alerts

    Returns:
        Dictionary with final processing status

    Example:
        >>> await simple_order_workflow({
            "id": "123",
            "notification_emails": ["admin@company.com"]
        })
    """
    try:
        # Phase 1: Create Order with built-in retries
        creation_result = await create_skb_order_task(order_data)

        if not creation_result.get("success"):
            await send_notification_task(
                {
                    "to_emails": order_data["notification_emails"],
                    "subject": "Order Creation Failed",
                    "message": f"Error: {creation_result.get('error_message')}",
                }
            )
            return creation_result

        # Initial pause before first check
        await pause_flow_run(
            timeout=1800,  # 30 minutes
            pause_key="initial-delay",
            reschedule=True,
        )

        # Phase 2: Poll result with simple retry logic
        for attempt in range(4):  # Total 5 attempts including initial
            try:
                result = await get_skb_order_result_task(creation_result)

                if result["success"]:
                    await send_notification_task(
                        {
                            "to_emails": order_data["notification_emails"],
                            "subject": "Order Completed",
                            "message": f"Order {order_data['id']} processed",
                        }
                    )
                    return result

                # Delay between subsequent attempts
                if attempt < 3:
                    await pause_flow_run(
                        timeout=900,  # 15 minutes
                        pause_key=f"retry-delay-{attempt}",
                        reschedule=True,
                    )
            except Exception as exc:
                if attempt == 3:
                    await send_notification_task(
                        {
                            "to_emails": order_data["notification_emails"],
                            "subject": "Final Attempt Failed",
                            "message": f"Error: {str(exc)}",
                        }
                    )
                    raise

        return {"status": "max_retries_exceeded"}

    except Exception as exc:
        await send_notification_task(
            {
                "to_emails": order_data["notification_emails"],
                "subject": "Workflow Failed",
                "message": f"Critical error: {str(exc)}",
            }
        )
        raise
