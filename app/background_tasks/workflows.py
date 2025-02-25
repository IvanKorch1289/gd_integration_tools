from asyncio import sleep

from prefect import flow

from app.background_tasks.tasks import (
    create_skb_order_task,
    get_skb_order_result_task,
    send_mail_task,
)


__all__ = (
    "skb_order_workflow",
    "send_mail_workflow",
    "create_skb_order_workflow",
    "get_skb_order_result_workflow",
)


@flow(name="send-mail-workflow")
async def send_mail_workflow(body: dict):
    await send_mail_task(body)


@flow(name="create-skb-order-workflow")
async def create_skb_order_workflow(body: dict):
    await create_skb_order_task(body)


@flow(name="get-skb-order-result-task-workflow")
async def get_skb_order_result_workflow(body: dict):
    await get_skb_order_result_task(body)


@flow(name="skb-order-workflow")
async def skb_order_workflow(body: dict):
    # Шаг 1: Создание заказа
    create_result = await create_skb_order_task(body)

    # Шаг 2: Получение результата с кастомными задержками
    final_result = None
    for attempt in range(5):
        try:
            if attempt == 0:
                # Первая попытка через 30 минут
                await sleep(1800)
            else:
                # Последующие попытки через 15 минут
                await sleep(900)

            final_result = await get_skb_order_result_task(create_result)
            break  # Успешный результат
        except Exception as exc:
            if attempt == 4:  # Последняя попытка
                await send_mail_task(
                    {
                        "to_emails": create_result["notification_emails"],
                        "subject": "Order Result Failed",
                        "message": f"Failed after 5 attempts: {exc}",
                    }
                )
                return

    # Успешное уведомление
    await send_mail_task(
        {
            "to_emails": final_result["notification_emails"],
            "subject": "Order Completed",
            "message": f"Order {final_result['original_id']} successfully processed",
        }
    )
