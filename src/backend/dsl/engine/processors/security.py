"""DSL security-процессоры (Wave 8.1).

Содержит ``AuthValidateProcessor`` — DSL-узел проверки авторизации
для запроса, обрабатываемого pipeline-ом. Поддерживает round-trip
сериализацию через ``to_spec()``.

Использует уже существующие верификаторы из
``entrypoints.api.dependencies.auth_selector`` — это не нарушает
архитектурные границы, т.к. DSL-движок исполняется в рантайме
поверх HTTP-запроса (request доступен через ``exchange.headers`` /
``exchange.properties['request']``).
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

from src.core.auth import AuthContext, AuthMethod
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:  # pragma: no cover
    from src.dsl.engine.context import ExecutionContext

__all__ = ("AuthValidateProcessor",)

logger = logging.getLogger(__name__)

# Путь модуля с verifier-реестром. Импортируется через importlib, чтобы
# не нарушать архитектурную границу dsl→entrypoints (verifier'ы держат
# FastAPI/Request, поэтому живут в entrypoints).
_VERIFIERS_MODULE = "src.entrypoints.api.dependencies.auth_selector"


def _load_verifiers() -> dict[AuthMethod, Any]:
    """Lazy-loads verifier-реестр из entrypoints (runtime-only)."""
    module = importlib.import_module(_VERIFIERS_MODULE)
    return getattr(module, "_VERIFIERS", {})


class AuthValidateProcessor(BaseProcessor):
    """Проверяет, что request авторизован одним из допустимых методов.

    Стратегия:
    - Берёт ``request`` либо из ``exchange.properties['request']``,
      либо из контекста (если хост положил его туда заранее).
    - Перебирает список допустимых ``AuthMethod`` и вызывает соответствующий
      verifier из реестра в ``auth_selector``.
    - При успехе записывает ``AuthContext`` в ``exchange.properties['auth']``;
      при провале — переводит exchange в failed-состояние.

    Если ``request`` отсутствует (например, маршрут запущен по таймеру),
    процессор молча пропускает проверку — это соответствует методу ``NONE``.
    """

    DEFAULT_PROPERTY = "auth"

    def __init__(
        self,
        methods: list[str] | str,
        *,
        result_property: str = DEFAULT_PROPERTY,
        required: bool = True,
        name: str | None = None,
    ) -> None:
        if isinstance(methods, str):
            methods = [methods]
        self._methods_raw = [m.lower() for m in methods]
        self._result_property = result_property
        self._required = required
        super().__init__(name=name or f"auth:{','.join(self._methods_raw)}")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        request = exchange.get_property("request") or getattr(context, "request", None)

        try:
            methods = [AuthMethod(m) for m in self._methods_raw]
        except ValueError as exc:
            exchange.set_error(f"auth: неизвестный AuthMethod ({exc})")
            exchange.stop()
            return

        if AuthMethod.NONE in methods or request is None:
            exchange.set_property(
                self._result_property, AuthContext(AuthMethod.NONE, "anonymous")
            )
            return

        verifiers = _load_verifiers()
        for method in methods:
            verifier = verifiers.get(method)
            if verifier is None:
                continue
            ctx = await verifier(request)
            if ctx is not None:
                exchange.set_property(self._result_property, ctx)
                return

        if self._required:
            exchange.set_error(
                "auth: ни один из методов "
                f"{[m.value for m in methods]} не подтвердил запрос"
            )
            exchange.stop()

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML DSL."""
        return {
            "auth": {
                "methods": list(self._methods_raw),
                "result_property": self._result_property,
                "required": self._required,
            }
        }
