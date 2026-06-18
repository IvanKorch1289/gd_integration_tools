"""Async HTTP-клиент для windows-worker Desktop RPA endpoints.

Wave: ``[wave:s8/k3-rpa-windows-desktop]``. Обращается к sidecar'у
(``backend.windows_worker.handlers.desktop_rpa_handler``) по REST для выполнения
``click`` / ``type`` / ``screenshot`` действий через pywinauto.

Используется из DSL-шага ``.desktop_rpa(app, action, params)``.

S164 W2 — Circuit Breaker + Retry (per ПРАВИЛО 6):
    ``execute()`` обёрнут в shared CB + tenacity retry с exponential
    backoff + jitter. Module-level singleton (не per-instance, т.к.
    client создаётся per-call в DesktopRpaProcessor).
"""

from __future__ import annotations

from typing import Any

import httpx

from src.backend.core.logging import get_logger
from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry

__all__ = ("DesktopRpaClient", "DesktopRpaError")

_logger = get_logger(__name__)

# Все поддерживаемые действия и соответствующие endpoint'ы worker'а.
SUPPORTED_ACTIONS: dict[str, str] = {
    "click": "/rpa/click",
    "type": "/rpa/type",
    "screenshot": "/rpa/screenshot",
}


class DesktopRpaError(RuntimeError):
    """Ошибка вызова desktop-RPA sidecar'а."""


# S164 W2: shared Circuit Breaker для всех instances DesktopRpaClient.
# Module-level singleton per purge pattern (smtp.py uses per-instance,
# но DesktopRpaClient создаётся per-call в DSL processor — instance
# breaker был бы short-lived и ineffective).
def _get_desktop_rpa_breaker():
    """Lazy-init CB singleton (avoid module-load side effects)."""
    return get_breaker_registry().get_or_create(
        "desktop_rpa_client",
        BreakerSpec(
            name="desktop_rpa_client",
            failure_threshold=5,
            recovery_timeout=30.0,
        ),
    )


# S164 W2: retry decorator (3 attempts, exponential 1s → 8s + jitter).
# ``on=(httpx.HTTPError, DesktopRpaError)`` — retry на transport + sidecar
# ошибки. Не retry на InvalidAction (programmer error).
async def _execute_with_protection(
    url: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    plugin: str,
) -> httpx.Response:
    """Internal helper: CB + retry wrapped HTTP POST.

    Lives outside class because retry decorator must be module-level
    (per S163 W3 W11 pitfall: ``@self.<attr>`` causes NameError — class
    body executes before __init__).
    """
    breaker = _get_desktop_rpa_breaker()
    async with breaker.guard():
        from src.backend.core.net.migration_helper import make_http_client

        async with make_http_client(
            timeout=timeout, plugin=plugin
        ) as http:
            return await http.post(url, json=params, headers=headers)


def _get_execute_with_retry() -> Any:
    """Lazy-initialized retry wrapper for _execute_with_protection."""
    from src.backend.infrastructure.resilience.retry import make_async_retry

    return make_async_retry(
        max_attempts=3,
        initial_backoff=1.0,
        multiplier=2.0,
        max_backoff=8.0,
        on=(httpx.HTTPError, DesktopRpaError),
    )(_execute_with_protection)


_execute_with_retry = None  # Will be lazily initialized


class DesktopRpaClient:
    """Тонкий async-клиент к windows-worker Desktop RPA.

    Args:
        base_url: URL sidecar'а (``http://windows-worker:9001``).
        api_key: Опц. API-key для аутентификации (header
            ``X-API-Key``).
        timeout: Connect+read timeout HTTP-запроса.
    """

    def __init__(
        self, base_url: str, *, api_key: str | None = None, timeout: float = 30.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Выполняет ``action`` (click/type/screenshot) на windows-worker.

        Args:
            action: Один из ``SUPPORTED_ACTIONS``.
            params: Тело запроса (см. Pydantic-модели handler'а).

        Returns:
            JSON-ответ worker'а.

        Raises:
            DesktopRpaError: Невалидный action / HTTP-ошибка / sidecar 503.
        """
        if action not in SUPPORTED_ACTIONS:
            raise DesktopRpaError(
                f"Unsupported action {action!r}; "
                f"поддерживаются: {sorted(SUPPORTED_ACTIONS)}"
            )

        url = f"{self._base_url}{SUPPORTED_ACTIONS[action]}"
        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        # S164 W2: wrapped CB + retry.
        try:
            global _execute_with_retry
            if _execute_with_retry is None:
                _execute_with_retry = _get_execute_with_retry()
            response = await _execute_with_retry(
                url,
                params=params,
                headers=headers,
                timeout=self._timeout,
                plugin="services/rpa/desktop_rpa",
            )
        except httpx.HTTPError as exc:
            raise DesktopRpaError(f"transport error к {url}: {exc}") from exc

        if response.status_code == 503:
            raise DesktopRpaError(
                "windows-worker недоступен (503): pywinauto не установлен "
                "или sidecar не на Windows."
            )
        if response.status_code >= 400:
            raise DesktopRpaError(
                f"{action} failed ({response.status_code}): {response.text[:200]}"
            )
        return response.json()
