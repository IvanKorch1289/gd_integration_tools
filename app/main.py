from app.infra.application.app_factory import create_app
from app.infra.application.broker import get_broker


app = create_app()

broker = get_broker()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        reload=True,  # Автоперезагрузка при изменении кода
        log_level="debug",  # Детальные логи
        use_colors=True,  # Цветные логи (только для терминала)
        workers=1,  # Для разработки достаточно 1 воркера
        limit_concurrency=1000,  # Лимит одновременных соединений
        timeout_keep_alive=30,  # Таймаут keep-alive соединений
    )
