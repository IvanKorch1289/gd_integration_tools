from asyncio import Lock, Queue, create_task, sleep
from contextlib import asynccontextmanager
from logging import DEBUG
from typing import Any, AsyncGenerator, Dict

from aiohttp import (
    AsyncResolver,
    ClientError,
    ClientResponse,
    ClientResponseError,
    ClientSession,
    ClientTimeout,
    FormData,
    TCPConnector,
)
from json_tricks import dumps, loads
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from time import monotonic

from app.config.constants import consts
from app.config.settings import settings
from app.utils.circuit_breaker import get_circuit_breaker
from app.utils.decorators.singleton import singleton


__all__ = ("HttpClient", "get_http_client")


@singleton
class HttpClient:
    """
    Продвинутый HTTP-клиент с интеллектуальным управлением соединениями.

    Особенности:
    - Пул соединений с keep-alive
    - Паттерн Circuit Breaker
    - Автоматическое управление жизненным циклом сессии
    - Механизм повтора с экспоненциальным откатом
    - Логирование запросов/ответов с маскировкой чувствительных данных
    - Сбор метрик производительности
    - Фоновая очистка соединений
    - Кэширование DNS
    """

    def __init__(self):
        """Инициализирует HTTP-клиент с настройками из конфигурации."""
        from app.utils.logging_service import request_logger

        self.settings = settings.http_base_settings
        self.connector: TCPConnector | None = None
        self.session: ClientSession | None = None
        self.last_activity: float = 0
        self.active_requests: int = 0
        self.session_lock = Lock()
        self.logger = request_logger
        self.circuit_breaker = get_circuit_breaker()
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0,
        }
        self._init_purging()

    # region Управление сессиями
    async def _ensure_session(self) -> None:
        """Поддерживает активную сессию с обновлением по активности."""
        async with self.session_lock:
            now = monotonic()
            if self.session is None or self.session.closed:
                self._create_new_session()
                self.logger.debug(
                    "Создана новая сессия",
                    extra={"session_id": id(self.session)},
                )
            self.last_activity = now

    def _should_renew_session(self, current_time: float) -> bool:
        """Определяет необходимость обновления сессии по таймауту активности."""
        session_expiry = self.settings.keepalive_timeout + 5
        return (
            self.session is None
            or self.session.closed
            or (
                current_time - self.last_activity > session_expiry
                and self.active_requests == 0
            )
        )

    def _create_new_session(self) -> None:
        """Инициализирует новую клиентскую сессию с настройками таймаутов."""
        self.connector = TCPConnector(
            limit=self.settings.limit,
            limit_per_host=self.settings.limit_per_host,
            ttl_dns_cache=self.settings.ttl_dns_cache,
            ssl=self.settings.ssl_verify,
            force_close=self.settings.force_close,
            keepalive_timeout=self.settings.keepalive_timeout,
            resolver=AsyncResolver(),
        )

        timeout = ClientTimeout(
            total=self.settings.total_timeout,
            connect=self.settings.connect_timeout,
            sock_read=self.settings.sock_read_timeout,
        )

        self.session = ClientSession(
            connector=self.connector,
            timeout=timeout,
            auto_decompress=True,
            trust_env=True,
            connector_owner=False,
        )

    async def _close_session(self) -> None:
        """Грациозно закрывает текущую сессию, если она активна."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug(
                "Сессия закрыта", extra={"session_id": id(self.session)}
            )
            self.session = None

    # endregion

    # region Обработка запросов
    async def make_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str] | None = None,
        json: Dict[str, Any] | None = None,
        params: Dict[str, Any] | None = None,
        data: Dict[str, Any] | str | bytes | None = None,
        auth_token: str | None = None,
        response_type: str = "json",
        raise_for_status: bool = True,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        total_timeout: float | None = None,
    ) -> Dict[str, Any]:
        start_time = monotonic()
        last_exception = None
        headers = await self._build_headers(auth_token, headers, data, json)
        request_data = await self._prepare_request_data(data, json)

        connect = connect_timeout or self.settings.connect_timeout
        read = read_timeout or self.settings.sock_read_timeout
        total = total_timeout or (connect + read)
        timeout = ClientTimeout(total=total, connect=connect, sock_read=read)

        retry_policy = retry(
            stop=stop_after_attempt(self.settings.max_retries + 1),
            wait=wait_exponential(
                multiplier=self.settings.retry_backoff_factor
            ),
            retry=(
                retry_if_exception_type(consts.RETRY_EXCEPTIONS)
                | retry_if_exception_type(ClientResponseError)
            ),
            before_sleep=before_sleep_log(self.logger, DEBUG),
            reraise=True,
        )

        @retry_policy
        async def _do_request():
            await self._ensure_session()
            if self.session is None:
                raise ClientError("Session not initialized")

            await self._log_request(method, url, headers, params, request_data)
            async with self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=request_data,
                timeout=timeout,
            ) as response:
                content = await self._process_response(response, response_type)
                await self._log_response(response, content)

                if raise_for_status:
                    response.raise_for_status()

                return await self._build_response_object(
                    response, content, start_time
                )

        try:
            result = await _do_request()
            self.circuit_breaker.record_success()
            return result
        except RetryError as exc:
            last_exception = exc.last_attempt.exception()

            if last_exception is None or not isinstance(
                last_exception, BaseException
            ):
                last_exception = ClientError("Unknown error during retry")

            self.circuit_breaker.record_failure()

            await self.circuit_breaker.check_state(
                max_failures=self.settings.circuit_breaker_max_failures,
                reset_timeout=self.settings.circuit_breaker_reset_timeout,
                exception_class=ClientError,
            )
            if raise_for_status:
                raise last_exception from exc
            return await self._handle_final_error(last_exception, start_time)
        except Exception as exc:
            last_exception = exc
            self.circuit_breaker.record_failure()
            await self.circuit_breaker.check_state(
                max_failures=self.settings.circuit_breaker_max_failures,
                reset_timeout=self.settings.circuit_breaker_reset_timeout,
                exception_class=ClientError,
            )
            if raise_for_status:
                raise
            return await self._handle_final_error(exc, start_time)
        finally:
            await self._update_metrics(
                start_time, success=last_exception is None
            )
            self.last_activity = monotonic()

    # endregion

    # region Вспомогательные методы
    async def _build_headers(
        self,
        auth_token: str | None,
        custom_headers: Dict[str, str] | None,
        data: Dict[str, Any] | str | bytes | None,
        json_data: Dict[str, Any] | None,
    ) -> Dict[str, str]:
        """Создает заголовки с автоматическим определением Content-Type."""
        headers = {
            "User-Agent": "HttpClient/1.0",
            "Accept-Encoding": "gzip, deflate, br",
        }

        if not custom_headers or "Content-Type" not in custom_headers:
            if json_data is not None:
                headers["Content-Type"] = "application/json"
            elif isinstance(data, dict):
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif isinstance(data, (str, bytes)):
                headers["Content-Type"] = "application/octet-stream"

        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        if custom_headers:
            headers.update(custom_headers)

        return headers

    async def _prepare_request_data(
        self,
        data: Dict[str, Any] | str | bytes | None,
        json_data: Dict[str, Any] | None,
    ) -> str | bytes | None:
        """Сериализует данные с учетом Content-Type."""
        from app.utils.utils import utilities

        if json_data is not None:
            return dumps(
                json_data,
                extra_obj_encoders=[utilities.custom_json_encoder],
            )
        elif isinstance(data, dict):
            form_data = FormData()
            for key, value in data.items():
                form_data.add_field(key, value)
            return bytes(form_data)
        elif isinstance(data, (str, bytes)):
            return data
        else:
            return None

    # endregion

    # region Логирование и метрики
    async def _log_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Dict[str, Any],
        data: str | bytes | None,
    ) -> None:
        """Логирует детали запроса с маскировкой чувствительных данных."""
        safe_headers = {
            k: "***MASKED***" if k.lower() == "authorization" else v
            for k, v in headers.items()
        }
        truncated_data = (
            str(data)[:200] + "..." if data and len(str(data)) > 200 else data
        )

        self.logger.debug(
            "Выполнение запроса",
            extra={
                "method": method,
                "url": url,
                "headers": safe_headers,
                "params": params,
                "data": truncated_data,
            },
        )

    async def _log_response(
        self, response: ClientResponse, content: Any
    ) -> None:
        """Логирует детали ответа с усечением содержимого."""
        self.logger.debug(
            "Получен ответ",
            extra={
                "status": response.status,
                "headers": dict(response.headers),
                "content": (
                    str(content)[:500] + "..."
                    if len(str(content)) > 500
                    else content
                ),
            },
        )

    async def _update_metrics(self, start_time: float, success: bool) -> None:
        """Обновляет метрики производительности."""
        duration = monotonic() - start_time
        self.metrics["total_requests"] += 1
        key = "successful_requests" if success else "failed_requests"
        self.metrics[key] += 1
        self.metrics["average_response_time"] = (
            0.9 * self.metrics["average_response_time"] + 0.1 * duration
        )

    # endregion

    # region Обработка ответов
    async def _build_response_object(
        self, response: ClientResponse, content: Any, start_time: float
    ) -> Dict[str, Any]:
        """Создает стандартизированный словарь ответа."""
        content_type = (
            response.headers.get("Content-Type", "")
            .lower()
            .split(";")[0]
            .strip()
        )

        return {
            "status_code": response.status,
            "data": content,
            "headers": dict(response.headers),
            "content_type": content_type,
            "elapsed": monotonic() - start_time,
        }

    async def _handle_final_error(
        self, exception: Exception | None, start_time: float
    ) -> Dict[str, Any]:
        """Создает ответ об ошибке после исчерпания попыток."""
        status_code = getattr(exception, "status", None)
        headers = dict(getattr(exception, "headers", {}))

        return {
            "status": status_code,
            "data": None,
            "headers": headers,
            "elapsed": monotonic() - start_time,
        }

    async def _process_response(
        self, response: ClientResponse, response_type: str
    ) -> Any:
        """Обрабатывает содержимое ответа в соответствии с типом."""
        content = await response.read()

        if response_type == "json":
            try:
                return loads(content.decode("utf-8"))
            except Exception as exc:
                self.logger.error(
                    f"Ошибка парсинга JSON: {str(exc)}",
                    extra={"content": content[:200], "error": str(exc)},
                )
                raise ValueError("Неверный JSON-ответ") from exc
        if response_type == "text":
            return content.decode(errors="replace")
        if response_type == "bytes":
            return content
        raise ValueError(f"Неподдерживаемый тип ответа: {response_type}")

    # endregion

    # region Управление соединениями
    def _init_purging(self) -> None:
        """Инициализирует задачу фоновой очистки соединений."""
        self.purging_queue = Queue()
        create_task(self._connection_purger())

    async def _connection_purger(self) -> None:
        """Фоновая задача для проверки и очистки неактивных соединений."""
        while True:
            try:
                await sleep(self.settings.purging_interval)
                if self.connector and self.settings.enable_connection_purging:
                    now = monotonic()
                    if (
                        now - self.last_activity
                        > self.settings.keepalive_timeout
                    ):
                        await self._close_session()
            except Exception as exc:
                self.logger.error(
                    f"Ошибка очистки соединений: {str(exc)}", exc_info=True
                )

    async def close(self) -> None:
        """Освобождает все сетевые ресурсы и соединения."""
        try:
            async with self.session_lock:
                if self.session and not self.session.closed:
                    await self.session.close()
                    self.logger.debug(
                        "Сессия закрыта",
                        extra={"session_id": id(self.session)},
                    )
                if self.connector and not self.connector.closed:
                    await self.connector.close()
        except Exception as exc:
            self.logger.error(
                f"Ошибка закрытия сетевых ресурсов: {str(exc)}", exc_info=True
            )

    # endregion


@asynccontextmanager
async def get_http_client() -> AsyncGenerator[HttpClient, None]:
    """
    Контекстный менеджер для HTTP-клиента с пулом соединений.

    Возвращает:
        Настроенный экземпляр HttpClient
    """
    client = HttpClient()
    try:
        yield client
    finally:
        # Не закрываем клиент, так как это синглтон
        pass
