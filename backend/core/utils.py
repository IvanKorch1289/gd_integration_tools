import json
import sys
import traceback
from typing import Any, Dict, List, TypeVar

import json_tricks
from fastapi import HTTPException, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import session_manager
from backend.core.logging_config import mail_logger
from backend.core.settings import settings


T = TypeVar("T")
ParamsType = Dict[str, Any]

cache_expire_seconds = settings.redis_settings.redis_cache_expire_seconds


def singleton(cls):
    """Декоратор для создания Singleton-класса.

    Args:
        cls: Класс, который нужно сделать Singleton.

    Returns:
        Функция, которая возвращает единственный экземпляр класса.
    """
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


@singleton
class Utilities:
    """Класс вспомогательных функций для работы с внешними сервисами и утилитами.

    Предоставляет методы для проверки состояния сервисов (база данных, Redis, S3 и т.д.),
    а также для выполнения задач, таких как отправка электронной почты.
    """

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def health_check_database(self, session: AsyncSession) -> bool:
        """Проверяет подключение к базе данных.

        Args:
            session (AsyncSession): Асинхронная сессия для выполнения запроса.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к базе данных не удалось.
        """
        try:
            result = await session.execute(text("SELECT 1"))
            if result.scalar_one_or_none() != 1:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database not connected",
                )
            return True
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database not connected: {str(exc)}",
            )

    async def health_check_redis(self) -> bool:
        """Проверяет подключение к Redis.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к Redis не удалось.
        """
        from backend.core.redis import redis_client

        try:
            async with redis_client.connection() as r:
                await r.ping()
            return True
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Redis not connected: {str(exc)}",
            )

    async def health_check_celery(self) -> bool:
        """Проверяет подключение к Celery.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к Celery не удалось.
        """
        try:
            from core.background_tasks import celery_app  # Ленивый импорт

            inspect = celery_app.control.inspect()
            ping_result = inspect.ping()

            if ping_result:
                return True
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Celery not connected",
                )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Celery not connected: {str(exc)}",
            )

    async def health_check_s3(self) -> bool:
        """Проверяет подключение к S3.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к S3 не удалось.
        """
        try:
            from backend.core.storage import \
                s3_bucket_service_factory  # Ленивый импорт

            s3_service = s3_bucket_service_factory()
            result = await s3_service.check_bucket_exists()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="S3 not connected",
                )
            return True
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 not connected: {str(exc)}",
            )

    async def health_check_scheduler(self) -> bool:
        """Проверяет подключение к планировщику задач.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к планировщику не удалось.
        """
        try:
            from backend.core.scheduler import \
                scheduler_manager  # Ленивый импорт

            result = await scheduler_manager.check_status()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Scheduler not connected",
                )
            return True
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Scheduler not connected: {str(exc)}",
            )

    async def health_check_graylog(self) -> bool:
        """Проверяет подключение к Graylog.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к Graylog не удалось.
        """
        try:
            import socket  # Ленивый импорт

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(
                (
                    settings.logging_settings.log_host,
                    settings.logging_settings.log_udp_port,
                )
            )
            sock.sendall(b"Healthcheck test message")
            sock.close()

            return True
        except OSError as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Graylog not connected: {str(exc)}",
            )

    async def health_check_smtp(self) -> bool:
        """Проверяет подключение к SMTP-серверу.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к SMTP не удалось.
        """
        try:
            import aiosmtplib  # Ленивый импорт

            hostname = settings.mail_settings.mail_hostname
            port = settings.mail_settings.mail_port
            use_tls = settings.mail_settings.mail_use_tls
            username = None if settings.app_debug else settings.mail_settings.mail_login
            password = None if settings.app_debug else settings.mail_settings.mail_login

            async with aiosmtplib.SMTP(
                hostname=hostname, port=port, use_tls=use_tls
            ) as smtp:
                if username and password:
                    await smtp.login(username, password)

            return True
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"SMTP not connected: {str(exc)}",
            )

    async def check_celery_queues(self) -> Dict[str, List[str]]:
        """
        Проверяет состояние очередей Celery.

        Returns:
            Dict[str, List[str]]: Состояние очередей Celery.
        """
        try:
            from core.background_tasks import celery_app  # Ленивый импорт

            inspect = celery_app.control.inspect()
            active_queues = inspect.active_queues()

            if not active_queues:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No active Celery queues found",
                )
            return active_queues
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to check Celery queues: {str(exc)}",
            )

    async def health_check_all_services(self):
        """Проверяет состояние всех сервисов (база данных, Redis, S3, Graylog, SMTP, Celery, планировщик задач).

        Returns:
            Response: JSON-ответ с результатами проверки всех сервисов.
        """
        db_check = await self.health_check_database()
        redis_check = await self.health_check_redis()
        s3_check = await self.health_check_s3()
        graylog_check = await self.health_check_graylog()
        smtp_check = await self.health_check_smtp()
        celery_check = await self.health_check_celery()
        celery_queue_check = await self.health_check_celery_queue()
        scheduler_check = await self.health_check_scheduler()

        response_data = {
            "db": db_check,
            "redis": redis_check,
            "s3": s3_check,
            "graylog": graylog_check,
            "smtp": smtp_check,
            "celery": celery_check,
            "celery_queue": celery_queue_check,
            "scheduler": scheduler_check,
        }

        if all(response_data.values()):
            status_code = 200
            message = "All systems are operational."
            is_all_services_active = True
        else:
            status_code = 500
            message = "One or more components are not functioning properly."
            is_all_services_active = False

        response_body = {
            "message": message,
            "is_all_services_active": is_all_services_active,
            "details": response_data,
        }

        return Response(
            content=json.dumps(response_body),
            media_type="application/json",
            status_code=status_code,
        )

    async def send_email(self, to_email: str, subject: str, message: str):
        """Отправляет электронное письмо на указанный адрес.

        Args:
            to_email (str): Адрес электронной почты получателя.
            subject (str): Тема письма.
            message (str): Текст письма.

        Returns:
            JSONResponse: Ответ с результатом отправки письма.
        """
        try:
            import aiosmtplib  # Ленивый импорт
            from email.header import Header
            from email.mime.text import MIMEText
            from email.utils import formataddr

            hostname = settings.mail_settings.mail_hostname
            port = settings.mail_settings.mail_port
            use_tls = settings.mail_settings.mail_use_tls
            username = None if settings.app_debug else settings.mail_settings.mail_login
            password = None if settings.app_debug else settings.mail_settings.mail_login
            sender = settings.mail_settings.mail_sender

            mail_logger.info(
                f"Sending email to {to_email} with subject '{subject}' and message '{message}'."
            )

            msg = MIMEText(message.encode("utf-8"), "plain", "utf-8")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = formataddr((str(Header("Отправитель", "utf-8")), sender))
            msg["To"] = to_email

            async with aiosmtplib.SMTP(
                hostname=hostname, port=port, use_tls=use_tls
            ) as smtp:
                if username and password:
                    await smtp.login(username, password)

                await smtp.send_message(msg)

            return JSONResponse({"status": "OK"})

        except Exception as exc:
            mail_logger.critical(f"Error for sending email to {to_email}: {str(exc)}.")
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def get_response_type_body(self, response: Response):
        """Извлекает и преобразует тело ответа в формат JSON.

        Args:
            response (Response): Ответ от сервера.

        Returns:
            Any: Тело ответа в формате JSON.
        """
        check_services_body = response.body.decode("utf-8")
        return json_tricks.loads(check_services_body)

    async def ensure_protocol(self, url: str) -> str:
        """
        Добавляет протокол (http://) к URL, если он отсутствует.

        Args:
            url (str): URL-адрес.

        Returns:
            str: URL с протоколом.
        """
        if not url.startswith(("http://", "https://")):
            return f"http://{url}"
        return url

    def generate_link_page(self, url: str, description: str) -> HTMLResponse:
        """
        Генерирует HTML-страницу с кликабельной ссылкой.

        Args:
            url (str): URL-адрес.
            description (str): Описание ссылки.

        Returns:
            HTMLResponse: HTML-страница с ссылкой.
        """
        return HTMLResponse(
            f"""
            <html>
                <body>
                    <p>Ссылка на {description}: <a href="{url}" target="_blank">{url}</a></p>
                </body>
            </html>
            """
        )


utilities = Utilities()
