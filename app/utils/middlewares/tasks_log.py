from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

from app.utils.logging_service import tasks_logger


__all__ = ("LoggingMiddleware",)


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
