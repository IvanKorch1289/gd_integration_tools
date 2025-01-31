# events.py
import json
import uuid

import redis
import threading
from celery import Celery
from celery.signals import task_postrun


class EventManager:
    def __init__(
        self,
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        celery_broker="redis://localhost:6379/0",
        celery_backend="redis://localhost:6379/0",
    ):
        # Инициализация Redis
        self.redis = redis.Redis(host=redis_host, port=redis_port, db=redis_db)

        # Инициализация Celery
        self.celery = Celery(
            "tasks", broker=celery_broker, backend=celery_backend
        )

        # Регистрация обработчиков событий
        self.handlers = {}

        # Запуск слушателя Redis в отдельном потоке
        self._start_listener()

        # Регистрация сигнала для очистки кэша
        self._register_cleanup_signal()

    def _register_cleanup_signal(self):
        """Регистрация сигнала для очистки кэша после выполнения задачи"""

        @task_postrun.connect
        def cleanup_cache(task_id, **kwargs):
            event_id = self.redis.get(f"celery-task-meta-{task_id}")
            if event_id:
                self.redis.delete(f"event:{event_id.decode()}")
                self.redis.delete(f"celery-task-meta-{task_id}")

    def _start_listener(self):
        """Запуск фонового потока для прослушивания событий"""

        def listener():
            pubsub = self.redis.pubsub()
            pubsub.subscribe("event_channel")
            for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        event_id = message["data"].decode()
                        event_data = self.redis.get(f"event:{event_id}")
                        if event_data:
                            data = json.loads(event_data)
                            self._process_event(data)
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Error processing message: {e}")

        thread = threading.Thread(target=listener, daemon=True)
        thread.start()

    def _process_event(self, data):
        """Обработка события и запуск соответствующего обработчика"""
        event_type = data.get("type")
        handler = self.handlers.get(event_type)
        if handler:
            event_id = data["event_id"]
            task = handler.apply_async(
                args=[data["payload"]], task_id=str(uuid.uuid4())
            )
            self.redis.set(f"celery-task-meta-{task.task_id}", event_id)
        else:
            print(f"No handler registered for event type: {event_type}")

    def register_handler(self, event_type, handler_func):
        """
        Регистрация обработчика событий с явной проверкой ошибок
        """
        # Создаем Celery задачу для обработчика
        task_name = f"handle_{event_type}"

        @self.celery.task(name=task_name)
        def wrapped_handler(payload):
            try:
                return handler_func(payload)
            except Exception as e:
                print(f"Error in handler {task_name}: {e}")
                raise

        self.handlers[event_type] = wrapped_handler

    def send_event(self, event_type, payload=None):
        """
        Регистрация события с сохранением в Redis и гарантией доставки
        """
        try:
            event_id = str(uuid.uuid4())
            event_data = json.dumps(
                {
                    "event_id": event_id,
                    "type": event_type,
                    "payload": payload or {},
                }
            )

            # Сохраняем событие в Redis
            self.redis.set(
                f"event:{event_id}",
                event_data,
                ex=3600,  # TTL 1 hour на случай проблем
            )

            # Публикуем ID события
            self.redis.publish("event_channel", event_id)

            return True
        except redis.RedisError as e:
            print(f"Failed to register event: {e}")
            return False


# Пример использования
if __name__ == "__main__":
    # Инициализация менеджера событий
    manager = EventManager()

    # Регистрация обработчиков с явным вызовом (можно обернуть в try-except)
    def handle_user_registration(payload):
        print(f"Processing registration for: {payload['email']}")
        # Логика обработки с возможными ошибками БД
        # ...

    try:
        manager.register_handler("user_registered", handle_user_registration)
    except Exception as e:
        print(f"Failed to register handler: {e}")

    # Отправка события с обработкой возможных ошибок
    success = manager.send_event(
        "user_registered", {"email": "user@example.com", "user_id": 123}
    )

    if not success:
        print("Failed to send event")
