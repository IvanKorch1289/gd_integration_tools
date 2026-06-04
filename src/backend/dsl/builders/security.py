"""Security / Auth миксин для RouteBuilder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import CallableProcessor


class SecurityMixin:
    """Поведенческий миксин security / auth.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

    def auth(
        self,
        methods: list[str] | str = "api_key",
        *,
        result_property: str = "auth",
        required: bool = True,
    ) -> RouteBuilder:
        """Проверяет авторизацию запроса (Wave 8.1).

        Args:
            methods: Один или список разрешённых AuthMethod
                (``api_key`` / ``jwt`` / ``express_jwt`` / ``mtls`` / ``basic``).
            result_property: Имя property для AuthContext.
            required: Если True — при провале маршрут останавливается.
        """
        from src.backend.dsl.engine.processors.security import AuthValidateProcessor

        return self._add(  # type: ignore[attr-defined]
            AuthValidateProcessor(
                methods=methods, result_property=result_property, required=required
            )
        )

    def require_header(self, name: str) -> RouteBuilder:
        """DX-2: валидирует присутствие header. Fail route если отсутствует.

        Usage::
            .require_header("Authorization")
        """

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            if not exchange.in_message.headers.get(name):
                exchange.fail(f"Missing required header: {name}")

        return self._add(  # type: ignore[attr-defined]
            CallableProcessor(_check, name=f"require_header:{name}")
        )

    def require_bearer(self) -> RouteBuilder:
        """DX-2: валидирует Bearer token в Authorization header."""

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            auth = exchange.in_message.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                exchange.fail("Missing or invalid Bearer token")
                return
            token = auth[7:].strip()
            if not token:
                exchange.fail("Empty Bearer token")
                return
            exchange.set_property("auth_token", token)

        return self._add(  # type: ignore[attr-defined]
            CallableProcessor(_check, name="require_bearer")
        )

    def require_auth(self) -> RouteBuilder:
        """DX-2: валидирует API key или Bearer token."""

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            auth = exchange.in_message.headers.get("Authorization", "")
            api_key = exchange.in_message.headers.get("X-API-Key", "")
            if not auth and not api_key:
                exchange.fail(
                    "Authentication required (Authorization or X-API-Key header)"
                )
                return
            exchange.set_property("authenticated", True)

        return self._add(  # type: ignore[attr-defined]
            CallableProcessor(_check, name="require_auth")
        )

    def require_fields(self, *names: str) -> RouteBuilder:
        """DX-2: валидирует что в body есть указанные поля.

        Usage::
            .require_fields("order_id", "customer_email")
        """
        required = tuple(names)

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            body = exchange.in_message.body
            if not isinstance(body, dict):
                exchange.fail(f"Body must be dict to check fields: {list(required)}")
                return
            missing = [f for f in required if f not in body]
            if missing:
                exchange.fail(f"Missing required fields: {missing}")

        return self._add(  # type: ignore[attr-defined]
            CallableProcessor(_check, name=f"require_fields:{','.join(required)}")
        )

    def jwt_sign(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        expires_in_seconds: int | None = 3600,
        output_property: str = "jwt",
    ) -> RouteBuilder:
        """Подпись payload как JWT-токен (PyJWT)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.enrichment",
            "JwtSignProcessor",
            secret_key=secret_key,
            algorithm=algorithm,
            expires_in_seconds=expires_in_seconds,
            output_property=output_property,
        )

    def jwt_verify(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        header: str = "Authorization",
        output_property: str = "jwt_claims",
    ) -> RouteBuilder:
        """Проверка JWT из заголовка; claims → property или fail."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.enrichment",
            "JwtVerifyProcessor",
            secret_key=secret_key,
            algorithm=algorithm,
            header=header,
            output_property=output_property,
        )

    def webhook_sign(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
    ) -> RouteBuilder:
        """HMAC-подпись outgoing webhook'а."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.enrichment",
            "WebhookSignProcessor",
            secret=secret,
            header=header,
            algorithm=algorithm,
        )

    def webhook_verify(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
        prefix: str | None = None,
        on_mismatch: str = "fail",
    ) -> RouteBuilder:
        """Верификация HMAC-подписи входящего webhook'а (timing-safe).

        ``on_mismatch="fail"`` (default) — fail pipeline; ``"warn"`` — лог
        предупреждения и установка ``webhook_signature_valid=False`` без
        остановки. ``prefix`` — опциональный схема-префикс (``"v1"``,
        ``"sha256"``), если подпись передаётся как ``v1=<hex>``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.enrichment",
            "WebhookSignVerifyProcessor",
            secret=secret,
            header=header,
            algorithm=algorithm,
            prefix=prefix if prefix is not None else "",
            on_invalid=on_mismatch,
        )

    def deadline(
        self, *, timeout_seconds: float = 30.0, fail_on_exceed: bool = True
    ) -> RouteBuilder:
        """Установка дedline pipeline; downstream проверяет _deadline_at."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.enrichment",
            "DeadlineProcessor",
            timeout_seconds=timeout_seconds,
            fail_on_exceed=fail_on_exceed,
        )

    def mask_pii(
        self,
        *,
        targets: list[str],
        fields: list[str] | None = None,
        replacement: str = "***",
        patterns: list[str] | None = None,
    ) -> RouteBuilder:
        """Маскировка PII в request/response (Sprint 8A K1 W4).

        Применяет PII-маскировку к выбранным частям ``Exchange``: body,
        headers, query, path. См. :class:`MaskPiiProcessor`.

        Args:
            targets: Список целей: ``body`` | ``headers`` | ``query`` | ``path``.
            fields: Опц. whitelist полей (по имени dict-ключа). ``None`` =
                маскируются все строковые значения.
            replacement: Строка-заменитель (default ``"***"``).
            patterns: Опц. список regex-строк. Если задан — заменяет
                дефолтные patterns. ``None`` = дефолты (8 типов PII).
        """
        from src.backend.dsl.engine.processors.mask_pii import MaskPiiProcessor

        return self._add(  # type: ignore[attr-defined]
            MaskPiiProcessor(
                targets=targets,
                fields=fields,
                replacement=replacement,
                patterns=patterns,
            )
        )
