from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

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
  ``_processors``, ``_protocol``, ``_transport_config``,
  ``_feature_flag``).
* приватные утилиты (``_add``, ``_add_lazy``, ``_last_processor_or_raise``,
  ``_set_first_attr``, ``_validate_action_names``) живут на
  ``RouteBuilder`` и доступны через ``self``.
"""


from src.backend.dsl.engine.processors import SetHeaderProcessor


class ConfigMixin:
    """configuration (with_timeout, with_retries, with_headers, with_auth, set_header) для RouteBuilder. S57 W1 extraction."""

    __slots__ = ()

    def with_timeout(self, seconds: float) -> RouteBuilder:
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
    ) -> RouteBuilder:
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

    def with_headers(
        self, headers: dict[str, str], *, mode: str = "merge"
    ) -> RouteBuilder:
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
    ) -> RouteBuilder:
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

    def set_header(self, key: str, value: Any) -> RouteBuilder:
        """Устанавливает заголовок в in_message."""
        return self._add(SetHeaderProcessor(key=key, value=value))
