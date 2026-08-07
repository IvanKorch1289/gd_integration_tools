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
from typing import TYPE_CHECKING, Any

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.logging import get_logger
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = ("AuthValidateProcessor",)


# cycle-2/D-AUDIT-03 fix: явный fail-closed exception при недоступности
# реестра verifiers. Раньше _load_verifiers возвращал {} — silent fail-open.
class AuthenticationProviderUnavailableError(RuntimeError):
    """Поднимается когда реестр verifiers недоступен.

    Pure ASGI fail-closed: DSL-роут с required=True падает в 401,
    required=False — в 503 (provider unavailable).
    """


# Путь модуля с verifier-реестром. Импортируется через importlib, чтобы
# не нарушать архитектурную границу dsl→entrypoints (verifier'ы держат
# FastAPI/Request, поэтому живут в entrypoints).
_VERIFIERS_MODULE = "src.backend.entrypoints.api.dependencies.auth_selector"

_logger = get_logger("dsl.security.auth")


def _load_verifiers() -> dict[AuthMethod, Any]:
    """Lazy-loads verifier-реестр из entrypoints (runtime-only).

    cycle-2/D-AUDIT-03 fix: pure ASGI fail-closed. При недоступности реестра
    (import error, missing ``_VERIFIERS``) поднимает
    :class:`AuthenticationProviderUnavailableError` вместо silent
    ``return {}`` (который ранее приводил к fail-open auth bypass).
    """
    try:
        module = importlib.import_module(_VERIFIERS_MODULE)
        verifiers = getattr(module, "_VERIFIERS", None)
        if verifiers is None:
            _logger.error(
                "auth_provider_unavailable: missing _VERIFIERS in %s",
                _VERIFIERS_MODULE,
            )
            raise AuthenticationProviderUnavailableError(
                f"verifier-реестр не сконфигурирован в {_VERIFIERS_MODULE}",
            )
        return verifiers
    except (ImportError, AttributeError) as exc:
        _logger.error(
            "auth_provider_unavailable: import failed: %s",
            exc,
        )
        raise AuthenticationProviderUnavailableError(
            f"verifier-реестр недоступен: {exc}",
        ) from exc


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
        """Проверяет аутентификацию запроса по списку auth-методов.

        Извлекает request из exchange/context, перебирает указанные auth-методы
        (JWT, API key, SAML и т.д.) через зарегистрированные verifiers.
        Первый успешный verifier формирует :class:`AuthContext` в свойстве
        ``result_property``. При ``AuthMethod.NONE`` или отсутствии request —
        anonymous-контекст.

        Args:
            exchange: Текущий exchange; request — из свойства ``request``.
                AuthContext — в свойстве ``result_property``.
            context: Контекст выполнения маршрута.
        """
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

        # cycle-2/D-AUDIT-03 fix: pure ASGI fail-closed при недоступности
        # реестра verifiers. AuthenticationProviderUnavailableError →
        # exchange.set_error + stop (DSL-движок возвращает 401/503).
        try:
            verifiers = _load_verifiers()
        except AuthenticationProviderUnavailableError as exc:
            exchange.set_error(
                f"auth: provider_unavailable: {exc}",
            )
            exchange.stop()
            return

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
