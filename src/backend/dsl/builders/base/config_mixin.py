from __future__ import annotations

from typing import Any, Self

from src.backend.dsl.builders.base._protocol import _RouteBuilderProtocol

"""Base-модуль RouteBuilder.

Содержит сам класс ``RouteBuilder`` (``@dataclass(slots=True)``) и его
core-методы: точки входа, ``_add`` / ``_add_lazy`` helpers, pipeline
composition (process / to / process_fn / include), chainable per-step
modifiers (with_timeout/retries/headers/auth), core-процессоры
(set_header/set_property/log/validate/feature_flag),
generic-helpers (shadow_mode/bulkhead/lineage/ab_test/feature_flag_branch),
business-helpers (tenant_scope/cost_tracker/outbox/mask/compliance_labels),
а также ``build()`` + ``_validate_action_names()``.

Контракт миксинов (см. ADR DSL Foundation Refactor 2026-05):

* mixin'ы — **stateless** поведенческие классы: только методы.
* mixin'ы **не имеют** ``@dataclass`` декоратора.
* mixin'ы **объявляют** пустой ``__slots__ = ()`` — обязательно для
  совместимости с ``RouteBuilder(@dataclass(slots=True))``: пустой tuple
  снимает ``__dict__`` overhead, не конфликтует с lay-out наследника
  и проходит ``mypy`` strict.
* mixin'ы **не имеют** instance-атрибутов; всё состояние живёт в
  ``RouteBuilder`` (``route_id``, ``source``, ``description``,
  ``_processors``, ``_protocol``, ``_transport_config``, ``_feature_flag``,
  ``_route_overrides``).
* приватные утилиты (``_add``, ``_add_lazy``, ``_last_processor_or_raise``,
  ``_set_first_attr``, ``_validate_action_names``) живут на
  ``RouteBuilder`` и доступны через ``self``.
"""


from src.backend.dsl.engine.processors import SetHeaderProcessor


class ConfigMixin(_RouteBuilderProtocol):
    """configuration (with_timeout, with_retries, with_headers, with_auth, with_pool_size, with_max_message_size, with_message_timeout, set_header) для RouteBuilder. S57 W1 extraction; S163 W14 — добавлены route-level override setters."""

    __slots__ = ()

    def with_timeout(self, seconds: float) -> Self:
        """Переопределяет timeout последнего step.

        Применимо к процессорам, имеющим атрибут ``_timeout`` или ``timeout``
        (HttpCallProcessor, DatabaseQueryProcessor и т.п.).

        Args:
            seconds: Таймаут в секундах (float).

        Raises:
            ValueError: если предыдущий processor не поддерживает timeout.

        Example::

            builder.http_call("https://api.example.com").with_timeout(10.0)
        """
        last = self._last_processor_or_raise()
        if self._set_first_attr(last, ("_timeout", "timeout"), float(seconds)) is None:
            raise ValueError(
                f"with_timeout: processor {type(last).__name__} "
                f"не поддерживает атрибут timeout"
            )
        return self

    def with_retries(
        self, max_attempts: int, *, backoff: str | float | None = None
    ) -> Self:
        """Переопределяет количество попыток retry для предыдущего step.

        Применимо к процессорам, имеющим атрибут ``_max_attempts``,
        ``_max_retries``, ``max_attempts`` или ``max_retries``.

        Args:
            max_attempts: Максимальное количество попыток (включая первую).
            backoff: Опциональный backoff. Тип зависит от processor: для
                ``RetryProcessor`` — строка ``fixed``/``exponential``; для
                кастомных процессоров может быть число.

        Raises:
            ValueError: если предыдущий processor не поддерживает retries.
        """
        last = self._last_processor_or_raise()
        applied = self._set_first_attr(
            last,
            ("_max_attempts", "_max_retries", "max_attempts", "max_retries"),
            int(max_attempts),
        )
        if applied is None:
            raise ValueError(
                f"with_retries: processor {type(last).__name__} "
                f"не поддерживает атрибут retries"
            )
        if backoff is not None:
            self._set_first_attr(
                last, ("_backoff", "_retry_backoff", "backoff"), backoff
            )
        return self

    def with_circuit_breaker(
        self, name: str, *, failure_threshold: int = 5, recovery_timeout: float = 30.0
    ) -> Self:
        """Переопределяет Circuit Breaker для предыдущего step (S168 W10 P1-4).

        Symmetric с ``with_timeout``/``with_retries``: mutates
        ``_circuit_breaker`` / ``breaker_name`` / ``circuit_breaker_name``
        на последнем processor (per ``_set_first_attr`` convention).

        Args:
            name: Имя BreakerSpec в ``BreakerRegistry`` (canonical через
                ``get_breaker_registry().get_or_create(name, spec)``).
            failure_threshold: Количество failures до open state.
            recovery_timeout: Seconds до half-open attempt.

        Raises:
            ValueError: если предыдущий processor не поддерживает CB.

        Example::

            builder.http_call("https://api.example.com").with_circuit_breaker(
                "external_api", failure_threshold=3, recovery_timeout=60.0
            )
        """
        # P9 fix: import via importlib to break circular chain
        # (breaker → core.logging → infrastructure.logging → core.interfaces → breaker).
        import importlib

        _breaker_mod = importlib.import_module("src.backend.core.resilience.breaker")
        BreakerSpec = _breaker_mod.BreakerSpec

        last = self._last_processor_or_raise()
        spec = BreakerSpec(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
        applied = self._set_first_attr(
            last, ("_circuit_breaker", "breaker_name", "circuit_breaker_name"), spec
        )
        if applied is None:
            raise ValueError(
                f"with_circuit_breaker: processor {type(last).__name__} "
                f"не поддерживает атрибут circuit_breaker"
            )
        return self

    def with_headers(self, headers: dict[str, str], *, mode: str = "merge") -> Self:
        """Переопределяет HTTP-заголовки предыдущего step.

        Args:
            headers: Словарь заголовков для применения.
            mode: ``merge`` (объединение, override duplicate) или ``replace``
                (полная замена).

        Raises:
            ValueError: если mode не ``merge``/``replace`` или processor не
                поддерживает атрибут headers.
        """
        if mode not in ("merge", "replace"):
            raise ValueError(
                f"with_headers: mode должен быть 'merge' или 'replace', "
                f"получено {mode!r}"
            )
        last = self._last_processor_or_raise()
        for attr in ("_headers", "headers"):
            if hasattr(last, attr):
                current = getattr(last, attr) or {}
                if mode == "replace":
                    setattr(last, attr, dict(headers))
                else:
                    merged = dict(current)
                    merged.update(headers)
                    setattr(last, attr, merged)
                return self
        raise ValueError(
            f"with_headers: processor {type(last).__name__} "
            f"не поддерживает атрибут headers"
        )

    def with_auth(
        self,
        *,
        token: str | None = None,
        api_key: str | None = None,
        mtls_cert: str | None = None,
    ) -> Self:
        """Переопределяет auth для предыдущего step.

        Поддерживается ровно один способ за вызов:
            - ``token``: Bearer-токен через ``_auth_token``.
            - ``api_key``: транслируется в header ``X-API-Key`` (через ``with_headers``).
            - ``mtls_cert``: путь к сертификату через ``_mtls_cert``.

        Raises:
            ValueError: если указано не ровно одно из значений или processor
                не поддерживает соответствующий атрибут.
        """
        provided = [v for v in (token, api_key, mtls_cert) if v is not None]
        if len(provided) != 1:
            raise ValueError(
                "with_auth: должен быть указан ровно один из token/api_key/mtls_cert"
            )
        if api_key is not None:
            return self.with_headers({"X-API-Key": api_key}, mode="merge")
        last = self._last_processor_or_raise()
        if token is not None:
            if self._set_first_attr(last, ("_auth_token", "auth_token"), token) is None:
                raise ValueError(
                    f"with_auth(token=...): processor {type(last).__name__} "
                    f"не поддерживает атрибут auth_token"
                )
            return self
        if mtls_cert is not None:
            if (
                self._set_first_attr(last, ("_mtls_cert", "mtls_cert"), mtls_cert)
                is None
            ):
                raise ValueError(
                    f"with_auth(mtls_cert=...): processor {type(last).__name__} "
                    f"не поддерживает атрибут mtls_cert"
                )
            return self
        return self

    def set_header(self, key: str, value: Any) -> Self:
        """Устанавливает заголовок в in_message."""
        return self._add(SetHeaderProcessor(key=key, value=value))

    # --- S163 W14: route-level override setters ---
    # Хранят значения в ``self._route_overrides`` (dict на RouteBuilder).
    # Используются per-step processors (через ``self.builder._route_overrides.get(...)``)
    # для override стандартных settings (timeout/pool/max_message_size/etc).
    #
    # Per-ROUTE override (НЕ per-step как ``with_timeout``):
    #   builder.from_("...").with_pool_size(50).proxy(...)  # pool=50 для всего route
    #
    # vs per-STEP override (existing):
    #   builder.from_("...").proxy(...).with_timeout(5.0)  # timeout только для proxy step

    def with_pool_size(self, n: int) -> Self:
        """Route-level override: pool size для всех транспортов в route.

        Используется в:
          * WS: max_connections (WSSettings.max_connections)
          * gRPC: max_concurrent_streams (GRPCSettings.max_concurrent_streams)
          * Kafka/Redis: pool_size из соответствующих settings
          * HTTP: max_connections через httpx.Limits

        Args:
            n: Размер пула (≥ 1).

        Returns:
            Self для chain.
        """
        if not isinstance(n, int) or n < 1:
            raise ValueError(f"with_pool_size: n должен быть int ≥ 1, получено {n!r}")
        self._route_overrides["pool_size"] = n
        return self

    def with_max_message_size(self, bytes_: int) -> Self:
        """Route-level override: max message size для WS/gRPC роутов.

        Используется в:
          * WS: WSSettings.max_message_size (default 64KB)
          * gRPC: GRPCSettings.max_message_size_bytes (default 4MB)

        Args:
            bytes_: Максимальный размер сообщения в байтах (≥ 1).

        Returns:
            Self для chain.
        """
        if not isinstance(bytes_, int) or bytes_ < 1:
            raise ValueError(
                f"with_max_message_size: bytes_ должен быть int ≥ 1, получено {bytes_!r}"
            )
        self._route_overrides["max_message_size"] = bytes_
        return self

    def with_message_timeout(self, seconds: float) -> Self:
        """Route-level override: per-message timeout для WS роутов.

        Используется в ws_handler через WSSettings.message_timeout_s.

        Args:
            seconds: Таймаут на одно WS-сообщение (секунды, > 0).

        Returns:
            Self для chain.
        """
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            raise ValueError(
                f"with_message_timeout: seconds должен быть > 0, получено {seconds!r}"
            )
        self._route_overrides["message_timeout_s"] = float(seconds)
        return self

    def get_route_override(self, key: str, default: Any = None) -> Any:
        """Читает route-level override (используется processors/handlers).

        Args:
            key: Имя параметра (e.g., 'pool_size', 'max_message_size').
            default: Default если override не задан.

        Returns:
            Значение override или default.
        """
        return self._route_overrides.get(key, default)

    def with_connection_pool(
        self, min_size: int = 2, max_size: int = 20, timeout: float = 5.0
    ) -> Self:
        """Route-level override: connection pool settings для всех транспортов.

        Позволяет настраивать min/max размер пула и timeout через DSL.

        Args:
            min_size: Минимальный размер пула (≥ 0).
            max_size: Максимальный размер пула (≥ 1).
            timeout: Timeout ожидания соединения (секунды, > 0).

        Returns:
            Self для chain.

        Example::

            builder.from_("http://api.example.com")
                .with_connection_pool(min_size=5, max_size=50, timeout=10.0)
                .proxy(...)
        """
        if not isinstance(min_size, int) or min_size < 0:
            raise ValueError(
                f"with_connection_pool: min_size должен быть int ≥ 0, получено {min_size!r}"
            )
        if not isinstance(max_size, int) or max_size < 1:
            raise ValueError(
                f"with_connection_pool: max_size должен быть int ≥ 1, получено {max_size!r}"
            )
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(
                f"with_connection_pool: timeout должен быть > 0, получено {timeout!r}"
            )
        self._route_overrides["connection_pool"] = {
            "min_size": min_size,
            "max_size": max_size,
            "timeout": timeout,
        }
        return self

    def with_reconnection(
        self, max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0
    ) -> Self:
        """Route-level override: reconnection policy для всех транспортов.

        Позволяет настраивать количество попыток переподключения,
        начальную задержку и коэффициент backoff через DSL.

        Args:
            max_attempts: Максимальное количество попыток переподключения (≥ 1).
            delay: Начальная задержка между попытками (секунды, > 0).
            backoff: Коэффициент умножения задержки (≥ 1.0).

        Returns:
            Self для chain.

        Example::

            builder.from_("ws://stream.example.com")
                .with_reconnection(max_attempts=5, delay=2.0, backoff=1.5)
                .websocket(...)
        """
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError(
                f"with_reconnection: max_attempts должен быть int ≥ 1, получено {max_attempts!r}"
            )
        if not isinstance(delay, (int, float)) or delay <= 0:
            raise ValueError(
                f"with_reconnection: delay должен быть > 0, получено {delay!r}"
            )
        if not isinstance(backoff, (int, float)) or backoff < 1.0:
            raise ValueError(
                f"with_reconnection: backoff должен быть ≥ 1.0, получено {backoff!r}"
            )
        self._route_overrides["reconnection"] = {
            "max_attempts": max_attempts,
            "delay": delay,
            "backoff": backoff,
        }
        return self
