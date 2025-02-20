__all__ = ("root_page",)


async def root_page():
    from app.config.settings import settings
    from app.utils.utils import utilities

    log_url = utilities.ensure_url_protocol(
        f"{settings.logging.host}:{settings.logging.port}"
    )
    fs_url = utilities.ensure_url_protocol(settings.storage.interface_endpoint)

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Добро пожаловать!</title>
        <style>
            body {{
                font-family: 'Arial', sans-serif;
                margin: 0;
                padding: 0;
                height: 100vh;
                background: linear-gradient(to bottom right, #e0f7e0 50%, #ffffff 50%);
                display: flex;
                justify-content: center;
                align-items: center;
                position: relative;
                overflow: hidden;
            }}
            body::before {{
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background:
                    radial-gradient(circle at 20% 20%, rgba(46, 125, 50, 0.1) 10%, transparent 10.5%),
                    radial-gradient(circle at 80% 20%, rgba(46, 125, 50, 0.1) 10%, transparent 10.5%),
                    radial-gradient(circle at 20% 80%, rgba(46, 125, 50, 0.1) 10%, transparent 10.5%),
                    radial-gradient(circle at 80% 80%, rgba(46, 125, 50, 0.1) 10%, transparent 10.5%);
                z-index: 1;
            }}
            body::after {{
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background:
                    radial-gradient(circle at 30% 30%, rgba(0, 123, 255, 0.1) 15%, transparent 15.5%),
                    radial-gradient(circle at 70% 30%, rgba(0, 123, 255, 0.1) 15%, transparent 15.5%),
                    radial-gradient(circle at 30% 70%, rgba(0, 123, 255, 0.1) 15%, transparent 15.5%),
                    radial-gradient(circle at 70% 70%, rgba(0, 123, 255, 0.1) 15%, transparent 15.5%);
                z-index: 1;
            }}
            .container {{
                text-align: center;
                background-color: rgba(255, 255, 255, 0.9);
                padding: 3rem;
                border-radius: 20px;
                box-shadow: 0 12px 24px rgba(0, 0, 0, 0.3);
                max-width: 700px;
                width: 90%;
                border: 2px solid #2e7d32;
                position: relative;
                z-index: 2;
            }}
            h1 {{
                font-size: 3rem;
                margin-bottom: 1.5rem;
                color: #2e7d32;
                text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
            }}
            p {{
                font-size: 1.3rem;
                margin-bottom: 2rem;
                color: #333;
                line-height: 1.6;
            }}
            .highlight {{
                font-weight: bold;
                color: #2e7d32;
                text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.1);
            }}
            a {{
                color: #007bff;
                text-decoration: none;
                font-weight: bold;
                border-bottom: 2px solid #007bff;
                transition: all 0.3s ease;
            }}
            a:hover {{
                color: #0056b3;
                border-bottom-color: #0056b3;
            }}
            .admin-link {{
                display: inline-block;
                margin-top: 1.5rem;
                padding: 0.75rem 1.5rem;
                background-color: #2e7d32;
                color: white;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                transition: background-color 0.3s ease;
            }}
            .admin-link:hover {{
                background-color: #1b5e20;
            }}
            .service-links {{
                margin-top: 2rem;
            }}
            .service-links a {{
                display: block;
                margin: 0.5rem 0;
                color: #2e7d32;
                text-decoration: none;
                font-weight: bold;
            }}
            .service-links a:hover {{
                color: #1b5e20;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Расширенные инструменты GreenData</h1>
            <p>
                Добро пожаловать в <span class="highlight">инновационное решение</span> для управления заказами, файлами и пользователями.
                Наше приложение сочетает в себе <span class="highlight">удобство</span>, <span class="highlight">надежность</span> и <span class="highlight">высокую производительность</span>.
            </p>
            <p>
                Для начала работы:
                <a href="/docs" target="_blank">Документация API</a>
                <a href="/asyncapi" target="_blank">Документация AsyncAPI</a>
            </p>
            <a href="/admin" class="admin-link" target="_blank">Перейти в административную панель</a>
            <div class="service-links">
                <h2>Технические интерфейсы</h2>
                <a href="{log_url}" target="_blank">Хранилище логов</a>
                <a href="{fs_url}" target="_blank">Файловое хранилище</a>
            </div>
        </div>
    </body>
    </html>
    """
