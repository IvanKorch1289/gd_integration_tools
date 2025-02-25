from prefect import task

from app.config.settings import settings
from app.services.route_services.orders import get_order_service
from app.utils.logging_service import tasks_logger


__all__ = (
    "send_mail_task",
    "create_skb_order_task",
    "get_skb_order_result_task",
)


@task
async def send_mail_task(body: dict) -> dict:
    from app.services.infra_services.mail import get_mail_service

    async with get_mail_service() as mail_service:
        return await mail_service.send_email(
            to_emails=body["to_emails"],
            subject=body["subject"],
            message=body["message"],
        )


@task(
    retries=settings.tasks.max_attempts,
    retry_delay_seconds=settings.tasks.seconds_delay,
)
async def create_skb_order_task(body: dict) -> dict:
    """Task for order creation"""
    try:
        result = await get_order_service().create_skb_order(
            order_id=body["id"]
        )

        if result.get("response", {}).get("status_code", {}) != 200:
            raise Exception("SKB order creation failed")

        return {
            **result,
            "notification_emails": body.get("email_for_answer", []),
            "id": body["id"],
        }
    except Exception:
        tasks_logger.error("Create order error", exc_info=True)
        raise


@task(
    retries=settings.tasks.max_attempts,
    retry_delay_seconds=settings.tasks.seconds_delay,
)
async def get_skb_order_result_task(body: dict) -> dict:
    """Task for result fetching"""
    try:
        result = await get_order_service().get_order_file_and_json_from_skb(
            order_id=body["id"], skb_id=body["object_uuid"]
        )

        if result.get("response", {}).get("status_code", {}) != 200:
            raise Exception("SKB order creation failed")

        return {
            "final_result": result,
            "notification_emails": body["email_for_answer"],
            "original_id": body["id"],
        }
    except Exception:
        tasks_logger.error("Get result error", exc_info=True)
        raise
