from celery import Celery


app = Celery("reports", broker="pyamqp://guest@localhost//")


@app.task(rate_limit="6/h", bind=True, max_retries=3, default_retry_delay=60)
def get_order_result_by_worker(self, order_id: int):
    pass
