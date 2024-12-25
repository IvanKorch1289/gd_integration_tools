import asyncio

from celery_app.config import celery_app, order_service_dependency


@celery_app.task(name="send_requests_by_one", bind=True)
def send_requests_by_one(self, order_id, retries_left=10):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            order_service_dependency().get_order_file_and_json(order_id=order_id)
        )
        if result is None or result == "SUCCESS":
            print("Успешная обработка заказа!")
            return
    except Exception as e:
        print(f"Произошла ошибка при обработке заказа: {e}")
    finally:
        loop.close()
    if retries_left > 1:
        self.apply_async(args=[order_id, retries_left - 1], countdown=60 * 20)
