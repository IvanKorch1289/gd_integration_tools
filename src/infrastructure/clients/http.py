import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from logging import DEBUG
from time import monotonic
from collections.abc import AsyncGenerator, Mapping
from typing import Any, BinaryIO, TypedDict

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
from app.utilities.json_codec import json_dumps
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config.constants import consts
from app.core.config.settings import settings
from app.core.decorators.singleton import singleton
from app.core.utils.circuit_breaker import get_circuit_breaker

__all__ = ("BaseHttpClient", "HttpClient", "get_http_client", "get_http_client_dependency")


class FilePart(TypedDict, total=False):
    content: bytes | bytearray | BinaryIO
    filename: str
    content_type: str


class BaseHttpClient(ABC):
    """Абстрактный базовый класс для HTTP-клиентов."""

    @abstractmethod
    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | str | bytes | None = None,
        files: Mapping[str, FilePart] | None = None,
        auth_token: str | None = None,
        response_type: str = "auto",
        raise_for_status: bool = True,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        total_timeout: float | None = None,
    ) -> dict[str, Any]:
        """Выполняет HTTP-запрос."""

    @abstractmethod
    async def close(self) -> None:
        """Закрывает соединения."""


@singleton
class HttpClient(BaseHttpClient):
    """
    HTTP-клиент с поддержкой:
    - keep-alive / connection pooling
    - retry
    - circuit breaker
    - multipart/form-data upload
    - автообработки json/text/bytes ответов
    """

    def __init__(self):
        from app.infrastructure.external_apis.logging_service import request_logger

        self.settings = settings.http_base_settings
        self.logger = request_logger

        self.connector: TCPConnector | None = None
        self.session: ClientSession | None = None

        self.last_activity: float = 0.0
        self.active_requests: int = 0
        self.session_lock = asyncio.Lock()
        self._metrics_lock = asyncio.Lock()
        self.purger_task: asyncio.Task | None = None

        self.circuit_breaker = get_circuit_breaker()
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0.0,
        }

    async def _ensure_session(self) -> None:
        async with self.session_lock:
            now = monotonic()

            if self.session is None or self.session.closed:
                self._create_new_session()
                self.logger.debug(
                    "Создана новая HTTP-сессия", extra={"session_id": id(self.session)}
                )

            self.last_activity = now
            self._start_purger_if_needed()

    def _create_new_session(self) -> None:
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

    def _start_purger_if_needed(self) -> None:
        if self.purger_task is None or self.purger_task.done():
            self.purger_task = asyncio.create_task(
                self._connection_purger(), name="http-client-connection-purger"
            )

    async def _close_session(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug(
                "HTTP-сессия закрыта", extra={"session_id": id(self.session)}
            )
        self.session = None

        if self.connector and not self.connector.closed:
            await self.connector.close()
        self.connector = None

    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | str | bytes | None = None,
        files: Mapping[str, FilePart] | None = None,
        auth_token: str | None = None,
        response_type: str = "auto",
        raise_for_status: bool = True,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        total_timeout: float | None = None,
    ) -> dict[str, Any]:
        start_time = monotonic()
        last_exception: Exception | None = None

        request_data = await self._prepare_request_data(
            data=data, json_data=json, files=files
        )

        headers = await self._build_headers(
            auth_token=auth_token,
            custom_headers=headers,
            json_data=json,
            data=data,
            files=files,
        )

        connect = connect_timeout or self.settings.connect_timeout
        read = read_timeout or self.settings.sock_read_timeout
        total = total_timeout or max(connect + read, connect, read)
        timeout = ClientTimeout(total=total, connect=connect, sock_read=read)

        retry_policy = retry(
            stop=stop_after_attempt(self.settings.max_retries + 1),
            wait=wait_exponential(multiplier=self.settings.retry_backoff_factor),
            retry=retry_if_exception(self._is_retryable_exception),
            before_sleep=before_sleep_log(self.logger, DEBUG),
            reraise=True,
        )

        @retry_policy
        async def _do_request():
            await self._ensure_session()
            if self.session is None:
                raise ClientError("Session not initialized")

            async with self._metrics_lock:
                self.active_requests += 1
            try:
                await self._log_request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    data=data,
                    files=files,
                )

                async with self.session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    params=params,
                    data=request_data,
                    timeout=timeout,
                ) as response:
                    if raise_for_status:
                        response.raise_for_status()

                    content = await self._process_response(
                        response=response, response_type=response_type
                    )

                    await self._log_response(response, content)

                    return await self._build_response_object(
                        response=response, content=content, start_time=start_time
                    )
            finally:
                async with self._metrics_lock:
                    self.active_requests -= 1
                self.last_activity = monotonic()

        try:
            result = await _do_request()
            self.circuit_breaker.record_success()
            return result
        except RetryError as exc:
            last_exception = exc.last_attempt.exception()
            if not isinstance(last_exception, Exception):
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
                start_time=start_time, success=last_exception is None
            )
            self.last_activity = monotonic()

    def _is_retryable_exception(self, exc: BaseException) -> bool:
        if isinstance(exc, ClientResponseError):
            return exc.status in {408, 409, 425, 429, 500, 502, 503, 504}

        return isinstance(exc, consts.RETRY_EXCEPTIONS)

    async def _build_headers(
        self,
        auth_token: str | None,
        custom_headers: dict[str, str] | None,
        json_data: dict[str, Any] | list[Any] | None,
        data: dict[str, Any] | str | bytes | None,
        files: Mapping[str, FilePart] | None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": "HttpClient/2.0",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
        }

        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        if custom_headers:
            headers.update(custom_headers)

        has_content_type = any(key.lower() == "content-type" for key in headers)

        if not has_content_type:
            if json_data is not None:
                headers["Content-Type"] = "application/json"
            elif isinstance(data, (str, bytes)):
                headers["Content-Type"] = "application/octet-stream"
            # Для dict-form и multipart руками Content-Type не ставим:
            # aiohttp выставит его сам корректно.

        if files:
            headers.pop("Content-Type", None)

        return headers

    async def _prepare_request_data(
        self,
        data: dict[str, Any] | str | bytes | None,
        json_data: dict[str, Any] | list[Any] | None,
        files: Mapping[str, FilePart] | None,
    ) -> Any:
        from app.utilities.utils import utilities

        if json_data is not None and (data is not None or files is not None):
            raise ValueError("json нельзя передавать вместе с data/files")

        if files:
            form = FormData()

            if isinstance(data, dict):
                for key, value in data.items():
                    form.add_field(key, "" if value is None else str(value))

            for field_name, file_part in files.items():
                form.add_field(
                    name=field_name,
                    value=file_part["content"],
                    filename=file_part.get("filename", field_name),
                    content_type=file_part.get(
                        "content_type", "application/octet-stream"
                    ),
                )

            return form

        if json_data is not None:
            return json_dumps(json_data)

        if isinstance(data, dict):
            return data

        if isinstance(data, (str, bytes)):
            return data

        return None

    async def _log_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        data: dict[str, Any] | str | bytes | None,
        files: Mapping[str, FilePart] | None,
    ) -> None:
        safe_headers = {
            key: (
                "***MASKED***"
                if key.lower()
                in {
                    "authorization",
                    "cookie",
                    "set-cookie",
                    "x-api-key",
                    "proxy-authorization",
                }
                else value
            )
            for key, value in headers.items()
        }

        truncated_data = data
        if isinstance(data, (str, bytes)):
            data_as_str = (
                data.decode("utf-8", errors="replace")
                if isinstance(data, bytes)
                else data
            )
            truncated_data = (
                data_as_str[:200] + "..." if len(data_as_str) > 200 else data_as_str
            )

        files_info = None
        if files:
            files_info = {}
            for field_name, file_part in files.items():
                content = file_part.get("content")
                size = None
                if isinstance(content, (bytes, bytearray)):
                    size = len(content)

                files_info[field_name] = {
                    "filename": file_part.get("filename"),
                    "content_type": file_part.get("content_type"),
                    "size": size,
                }

        self.logger.debug(
            "Выполнение HTTP-запроса",
            extra={
                "method": method.upper(),
                "url": url,
                "headers": safe_headers,
                "params": params,
                "data": truncated_data if files is None else None,
                "files": files_info,
            },
        )

    async def _log_response(self, response: ClientResponse, content: Any) -> None:
        content_repr = str(content)
        if len(content_repr) > 500:
            content_repr = content_repr[:500] + "..."

        self.logger.debug(
            "Получен HTTP-ответ",
            extra={
                "status": response.status,
                "headers": dict(response.headers),
                "content": content_repr,
            },
        )

    async def _update_metrics(self, start_time: float, success: bool) -> None:
        duration = monotonic() - start_time
        self.metrics["total_requests"] += 1
        key = "successful_requests" if success else "failed_requests"
        self.metrics[key] += 1
        self.metrics["average_response_time"] = (
            0.9 * self.metrics["average_response_time"] + 0.1 * duration
        )

    async def _build_response_object(
        self, response: ClientResponse, content: Any, start_time: float
    ) -> dict[str, Any]:
        content_type = (
            response.headers.get("Content-Type", "").lower().split(";")[0].strip()
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
    ) -> dict[str, Any]:
        status_code = getattr(exception, "status", None)
        headers = dict(getattr(exception, "headers", {}))

        return {
            "status_code": status_code,
            "data": None,
            "headers": headers,
            "elapsed": monotonic() - start_time,
            "error": str(exception) if exception else None,
        }

    async def _process_response(
        self, response: ClientResponse, response_type: str
    ) -> Any:
        if response_type == "bytes":
            return await response.read()

        if response_type == "text":
            return await response.text(errors="replace")

        if response_type == "json":
            return await response.json(content_type=None)

        if response_type == "auto":
            content_type = response.headers.get("Content-Type", "").lower()
            if "json" in content_type:
                return await response.json(content_type=None)
            return await response.text(errors="replace")

        raise ValueError(f"Неподдерживаемый тип ответа: {response_type}")

    async def _connection_purger(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.settings.purging_interval)

                if not self.settings.enable_connection_purging:
                    continue

                if self.active_requests != 0:
                    continue

                if monotonic() - self.last_activity > self.settings.keepalive_timeout:
                    async with self.session_lock:
                        await self._close_session()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(f"Ошибка очистки соединений: {exc}", exc_info=True)

    async def close(self) -> None:
        try:
            if self.purger_task:
                self.purger_task.cancel()
                try:
                    await self.purger_task
                except asyncio.CancelledError:
                    pass
                self.purger_task = None

            async with self.session_lock:
                await self._close_session()
        except Exception as exc:
            self.logger.error(f"Ошибка закрытия сетевых ресурсов: {exc}", exc_info=True)


@asynccontextmanager
async def get_http_client() -> AsyncGenerator[HttpClient, None]:
    client = HttpClient()
    yield client


def get_http_client_dependency() -> HttpClient:
    return HttpClient()
