from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from collections.abc import Mapping
from logging import DEBUG
from time import monotonic

import httpx
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.backend.core.config.constants import consts


class RequestMixin:
    """request execution (make_request BIG 118 LOC, retry check, final error handler) для HttpClient. S61 W4 extraction."""

    __slots__ = ()

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

        request_kwargs = await self._prepare_request_kwargs(
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
        timeout = httpx.Timeout(connect=connect, read=read, write=read, pool=total)

        retry_policy = retry(
            stop=stop_after_attempt(self.settings.max_retries + 1),
            wait=wait_exponential(multiplier=self.settings.retry_backoff_factor),
            retry=retry_if_exception(self._is_retryable_exception),
            before_sleep=before_sleep_log(self.logger, DEBUG),
            reraise=True,
        )

        @retry_policy
        async def _do_request() -> dict[str, Any]:
            await self._ensure_session()
            if self.client is None:
                raise httpx.RequestError("Session not initialized")

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
                response = await self.client.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=timeout,
                    **request_kwargs,
                )
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
                last_exception = httpx.RequestError("Unknown error during retry")

            self.circuit_breaker.record_failure()
            await self.circuit_breaker.check_state(
                max_failures=self.settings.circuit_breaker_max_failures,
                reset_timeout=self.settings.circuit_breaker_reset_timeout,
                exception_class=httpx.HTTPError,
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
                exception_class=httpx.HTTPError,
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
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
            return True
        return isinstance(exc, consts.RETRY_EXCEPTIONS)

    async def _handle_final_error(
        self, exception: Exception | None, start_time: float
    ) -> dict[str, Any]:
        status_code: int | None = None
        headers: dict[str, str] = {}
        if isinstance(exception, httpx.HTTPStatusError):
            status_code = exception.response.status_code
            headers = dict(exception.response.headers)
        return {
            "status_code": status_code,
            "data": None,
            "headers": headers,
            "elapsed": monotonic() - start_time,
            "error": str(exception) if exception else None,
        }
