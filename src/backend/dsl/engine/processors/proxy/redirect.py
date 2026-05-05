"""RedirectProcessor — HTTP-перенаправление в DSL-маршруте.

Режимы:
    static   — фиксированный redirect на ``target_url`` с заданным ``status_code``.
    proxy    — URL берётся из источника: header, body_field, exchange_var, query_param.

Процессор устанавливает:
    exchange.properties["_http_status_code"] — HTTP-статус (301/302/307/308).
    exchange.properties["_redirect_to"]      — URL назначения.
    exchange.out_message.headers["Location"] — Location-заголовок для HTTP-клиента.

После этого вызывает ``exchange.stop()``, останавливая дальнейшие шаги маршрута.

Использование в YAML::

    - kind: redirect
      config:
        mode: static
        status_code: 301
        target_url: /api/v2/payments

    - kind: redirect
      config:
        mode: proxy
        url_source: header
        source_key: X-Redirect-To

    - kind: redirect
      config:
        mode: proxy
        url_source: query_param
        source_key: redirect_uri
        allowed_hosts:
          - example.com
          - partner.org
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("RedirectProcessor",)

_logger = logging.getLogger("dsl.proxy.redirect")

_ALLOWED_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_URL_SOURCES = frozenset({"header", "body_field", "exchange_var", "query_param"})


class RedirectProcessor(BaseProcessor):
    """Выполняет HTTP-redirect внутри DSL-маршрута.

    Args:
        mode: Режим — ``static`` (фиксированный URL) или ``proxy`` (URL из источника).
        status_code: HTTP-статус редиректа (301/302/307/308). По умолчанию 302.
        target_url: URL для ``mode=static``. Обязателен при ``mode=static``.
        url_source: Источник URL для ``mode=proxy``:
            ``header`` | ``body_field`` | ``exchange_var`` | ``query_param``.
        source_key: Ключ/путь для извлечения URL из источника.
        allowed_hosts: Белый список хостов (проверка для ``url_source=query_param``).
            ``None`` — без ограничений.
        name: Имя процессора в трассе.
    """

    def __init__(
        self,
        *,
        mode: str = "static",
        status_code: int = 302,
        target_url: str | None = None,
        url_source: str | None = None,
        source_key: str | None = None,
        allowed_hosts: list[str] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        if mode not in {"static", "proxy"}:
            raise ValueError(
                f"RedirectProcessor: неверный mode={mode!r}. Ожидается 'static' или 'proxy'."
            )
        if status_code not in _ALLOWED_STATUS_CODES:
            raise ValueError(
                f"RedirectProcessor: недопустимый status_code={status_code}. "
                f"Допустимые: {sorted(_ALLOWED_STATUS_CODES)}."
            )
        if mode == "static" and not target_url:
            raise ValueError(
                "RedirectProcessor: target_url обязателен при mode='static'."
            )
        if mode == "proxy":
            if not url_source:
                raise ValueError(
                    "RedirectProcessor: url_source обязателен при mode='proxy'."
                )
            if url_source not in _URL_SOURCES:
                raise ValueError(
                    f"RedirectProcessor: неверный url_source={url_source!r}. "
                    f"Допустимые: {sorted(_URL_SOURCES)}."
                )
            if not source_key:
                raise ValueError(
                    "RedirectProcessor: source_key обязателен при mode='proxy'."
                )

        self._mode = mode
        self._status_code = status_code
        self._target_url = target_url
        self._url_source = url_source
        self._source_key = source_key
        self._allowed_hosts: frozenset[str] = (
            frozenset(allowed_hosts) if allowed_hosts else frozenset()
        )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Вычисляет URL редиректа и завершает маршрут с Location-заголовком."""
        url = (
            self._resolve_static()
            if self._mode == "static"
            else self._resolve_proxy(exchange)
        )
        if self._allowed_hosts and not self._is_allowed(url):
            _logger.warning(
                "RedirectProcessor: заблокирован redirect на %r (не в allowed_hosts).",
                url,
            )
            exchange.fail(
                f"Redirect заблокирован: хост {urlparse(url).hostname!r} не в белом списке."
            )
            return

        exchange.set_property("_http_status_code", self._status_code)
        exchange.set_property("_redirect_to", url)
        exchange.set_out(body=None, headers={"Location": url})
        exchange.stop()
        _logger.debug("RedirectProcessor: %s → %s", self._status_code, url)

    # -- Вспомогательные методы -----------------------------------------------

    def _resolve_static(self) -> str:
        return self._target_url  # type: ignore[return-value]

    def _resolve_proxy(self, exchange: Exchange[Any]) -> str:
        match self._url_source:
            case "header":
                url = exchange.in_message.headers.get(self._source_key)
            case "body_field":
                url = self._extract_body_field(
                    exchange.in_message.body, self._source_key
                )
            case "exchange_var":
                url = self._extract_exchange_var(exchange, self._source_key)
            case "query_param":
                url = exchange.in_message.headers.get(f"__query_{self._source_key}")
            case _:
                raise ValueError(f"Неизвестный url_source: {self._url_source!r}")

        if not url:
            raise ValueError(
                f"RedirectProcessor: не удалось получить URL из {self._url_source!r} / {self._source_key!r}."
            )
        return str(url)

    @staticmethod
    def _extract_body_field(body: Any, path: str) -> Any:
        """Извлекает значение из тела по точечному пути (``a.b.c``)."""
        if not isinstance(body, dict):
            return None
        node: Any = body
        for part in path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node

    @staticmethod
    def _extract_exchange_var(exchange: Exchange[Any], path: str) -> Any:
        """Извлекает значение из exchange.properties по точечному пути."""
        parts = path.split(".", 1)
        value = exchange.get_property(parts[0])
        if len(parts) == 1 or not isinstance(value, dict):
            return value
        return RedirectProcessor._extract_body_field(value, parts[1])

    def _is_allowed(self, url: str) -> bool:
        """Проверяет, разрешён ли хост в allowed_hosts."""
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host in self._allowed_hosts

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации RedirectProcessor."""
        spec: dict = {"status_code": self._status_code}
        if self._mode == "static":
            spec["target_url"] = self._target_url
        else:
            spec["url_source"] = self._url_source
            spec["source_key"] = self._source_key
            if self._allowed_hosts:
                spec["allowed_hosts"] = sorted(self._allowed_hosts)
        return {"redirect": spec}
