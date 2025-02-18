from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult
from taskiq_pipelines import Pipeline, PipelineMiddleware
from taskiq_redis import ListQueueBroker

from app.config.constants import RETRY_POLICY
from app.config.settings import settings
from app.services.infra_services.mail import get_mail_service
from app.services.route_services.orders import get_order_service
from app.utils.logging_service import tasks_logger


broker = ListQueueBroker(
    url=f"{settings.redis.redis_url}/{settings.redis.db_tasks}",
    queue_name=settings.redis.name_tasks_queue,
)


class LoggingMiddleware(TaskiqMiddleware):
    async def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        tasks_logger.info(
            f"[Start] Task {message.task_name} :: ID {message.task_id}"
        )
        return message

    async def post_send(self, message: TaskiqMessage) -> TaskiqMessage:  # type: ignore
        tasks_logger.info(
            f"[Success] Task {message.task_name} :: ID {message.task_id}"
        )

    def post_save(  # type: ignore
        self, message: TaskiqMessage, result: TaskiqResult
    ) -> TaskiqMessage:
        tasks_logger.info(
            f"[Result] Task {message.task_name} :: ID {message.task_id} :: result {result}"
        )

    async def on_error(  # type: ignore
        self, message: TaskiqMessage, error: Exception
    ) -> TaskiqMessage:
        tasks_logger.error(
            f"[FAILED] Task {message.task_name} :: ID {message.task_id} :: {error}"
        )


broker.add_middlewares(LoggingMiddleware())
broker.add_middlewares(PipelineMiddleware())


@broker.task(retry=RETRY_POLICY)
async def send_mail_task(body: dict) -> dict:
    async with get_mail_service() as mail_service:
        return await mail_service.send_email(
            to_emails=body["to_emails"],
            subject=body["subject"],
            message=body["message"],
        )


# @broker.task(retry=RETRY_POLICY)
# async def create_skb_order_task(ctx: dict) -> dict:
#     """
#     Задача для создания заказа в SKB с повторными попытками.
#     """
#     order_id = ctx["order_id"]

#     result = await get_order_service().create_skb_order(order_id=order_id)

#     if not result.get("data", {}).get("Result"):
#         raise RuntimeError("SKB order creation failed")

#     return {"order_id": order_id, "initial_result": result}


# @broker.task(retry=RETRY_POLICY)
# async def get_skb_order_result_task(ctx: dict) -> dict:
#     """
#     Задача для получения результата с повторными попытками.
#     """
#     order_id = ctx["order_id"]

#     result = await get_order_service().get_order_result(order_id=order_id)

#     # Кастомная проверка результата
#     if result.get("status") != "completed":
#         raise ValueError("Order result not ready")

#     return {"final_result": result}


# # Создаем пайплайн
# skb_order_pipeline = (
#     Pipeline(broker)
#     .call_next(create_skb_order_task)
#     .call_next(get_skb_order_result_task)
# )
