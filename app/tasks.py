from fastapi import Depends
from taskiq import TaskiqDepends
from taskiq_redis import ListQueueBroker


# Инициализируем Redis брокер с использованием списка как очереди.
broker = ListQueueBroker(
    "redis://localhost:6379",
    queue_name="task_queue",  # Название Redis-списка для задач
)
