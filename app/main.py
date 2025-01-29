from app.infra.app_factory import create_app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Автоперезагрузка при изменении кода
        debug=True,  # Подробные ошибки и трассировка
        log_level="debug",  # Детальные логи
        use_colors=True,  # Цветные логи (только для терминала)
        workers=1,  # Для разработки достаточно 1 воркера
        limit_concurrency=1000,  # Лимит одновременных соединений
        timeout_keep_alive=30,  # Таймаут keep-alive соединений
    )
