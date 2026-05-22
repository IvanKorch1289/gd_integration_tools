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

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src.backend.dsl.adapters.types import ProtocolType, TransportConfig
from src.backend.dsl.builders.ai_rpa import AIRPAMixin
from src.backend.dsl.builders.control_flow import ControlFlowMixin
from src.backend.dsl.builders.converters import ConvertersMixin
from src.backend.dsl.builders.eip import EIPMixin
from src.backend.dsl.builders.integration import IntegrationMixin
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    BaseProcessor,
    CallableProcessor,
    LogProcessor,
    ProcessorCallable,
    SetHeaderProcessor,
    SetPropertyProcessor,
    ValidateProcessor,
)

__all__ = ("RouteBuilder",)


@dataclass(slots=True)
class RouteBuilder(
    AIRPAMixin, ControlFlowMixin, EIPMixin, IntegrationMixin, ConvertersMixin
):
    """Fluent-builder для DSL-маршрутов.

    Пример::

        route = (
            RouteBuilder.from_("tech.send_email", source="internal:tech")
            .dispatch_action("tech.send_email")
            .log()
            .build()
        )
    """

    route_id: str
    source: str | None = None
    description: str | None = None
    _processors: list[BaseProcessor] = field(default_factory=list)
    _protocol: ProtocolType | None = None
    _transport_config: TransportConfig | None = None
    _feature_flag: str | None = None

    # ── Core helpers ──

    @classmethod
    def from_(
        cls, route_id: str, source: str, *, description: str | None = None
    ) -> "RouteBuilder":
        """Точка входа: создаёт новый RouteBuilder.

        Args:
            route_id: Уникальный ID маршрута (e.g., "orders.create").
            source: Источник данных (e.g., "internal:orders", "timer:60s", "webhook:/path").
            description: Человекочитаемое описание маршрута.

        Returns:
            RouteBuilder для fluent-chain вызовов.

        Example::

            route = (
                RouteBuilder.from_("etl.import", source="timer:300s")
                .http_call("https://api.example.com/data")
                .normalize()
                .dispatch_action("analytics.insert_batch")
                .build()
            )
        """
        return cls(route_id=route_id, source=source, description=description)

    @classmethod
    def from_registered_source(
        cls, route_id: str, source_id: str, *, description: str | None = None
    ) -> "RouteBuilder":
        """Точка входа W23: маршрут запитывается от зарегистрированного Source.

        Связь Source → DSL делается на уровне ``services.sources.lifecycle``
        через :class:`SourceToInvokerAdapter`; этот метод нужен только
        для **декларации** в DSL ("этот route ждёт события от source X")
        и метаданных ``Pipeline``.

        Args:
            route_id: Уникальный ID маршрута.
            source_id: ID source-инстанса в :class:`SourceRegistry`.
            description: Человекочитаемое описание.

        Example::

            route = (
                RouteBuilder.from_registered_source("orders.audit", "orders_cdc")
                .normalize()
                .dispatch_action("analytics.insert_batch")
                .build()
            )
        """
        return cls(
            route_id=route_id, source=f"source:{source_id}", description=description
        )

    def _add(self, processor: BaseProcessor) -> "RouteBuilder":
        self._processors.append(processor)
        return self

    def _add_lazy(
        self, import_path: str, class_name: str, **kwargs: Any
    ) -> "RouteBuilder":
        """Lazy import + создание процессора. Для AI/Web/Export/Integration."""
        import importlib

        mod = importlib.import_module(import_path)
        cls = getattr(mod, class_name)
        return self._add(cls(**kwargs))

    # ── Pipeline composition ──

    def process(self, processor: BaseProcessor) -> "RouteBuilder":
        """Добавляет произвольный процессор в pipeline."""
        return self._add(processor)

    def to(self, processor: BaseProcessor) -> "RouteBuilder":
        """Алиас для process() — fluent naming."""
        return self._add(processor)

    def process_fn(
        self, func: ProcessorCallable, *, name: str | None = None
    ) -> "RouteBuilder":
        """Добавляет обычную функцию или coroutine как процессор.

        Функция принимает (exchange, context) и модифицирует exchange in-place.
        """
        return self._add(CallableProcessor(func=func, name=name))

    def include(self, other: Pipeline) -> "RouteBuilder":
        """Включает все процессоры из другого Pipeline (композиция)."""
        self._processors.extend(other.processors)
        return self

    # ── Chainable per-step modifiers (Sprint 2 §12.5) ──

    def _last_processor_or_raise(self) -> BaseProcessor:
        """Возвращает последний добавленный processor для chainable-модификации.

        Raises:
            ValueError: если pipeline пуст — модификатор вызван до первого step.
        """
        if not self._processors:
            raise ValueError(
                "with_*-модификатор вызван до первого step — нет предыдущего "
                "processor для модификации"
            )
        return self._processors[-1]

    @staticmethod
    def _set_first_attr(
        obj: Any, candidates: tuple[str, ...], value: Any
    ) -> str | None:
        """Устанавливает значение в первый из существующих candidate-атрибутов."""
        for attr in candidates:
            if hasattr(obj, attr):
                setattr(obj, attr, value)
                return attr
        return None

    def with_timeout(self, seconds: float) -> "RouteBuilder":
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
    ) -> "RouteBuilder":
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
    ) -> "RouteBuilder":
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
    ) -> "RouteBuilder":
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

    # ── Core processors ──

    def set_header(self, key: str, value: Any) -> "RouteBuilder":
        """Устанавливает заголовок в in_message."""
        return self._add(SetHeaderProcessor(key=key, value=value))

    def set_property(self, key: str, value: Any) -> "RouteBuilder":
        """Устанавливает runtime-свойство Exchange."""
        return self._add(SetPropertyProcessor(key=key, value=value))

    def log(self, level: str = "info") -> "RouteBuilder":
        """Логирование текущего состояния Exchange (для отладки)."""
        return self._add(LogProcessor(level=level))

    def validate(self, model: type) -> "RouteBuilder":
        """Pydantic-валидация body; при ошибке Exchange останавливается."""
        return self._add(ValidateProcessor(model=model))

    # ── Feature-flag metadata ──

    def feature_flag(self, name: str) -> "RouteBuilder":
        """Привязывает маршрут к feature flag (можно отключить без рестарта)."""
        self._feature_flag = name
        return self

    # ── Generic (универсальные) helpers ──

    def shadow_mode(self, processors: list[BaseProcessor]) -> "RouteBuilder":
        """Исполняет вложенную ветку в shadow-режиме (без side effects)."""
        from src.backend.dsl.engine.processors.generic import ShadowModeProcessor

        return self._add(ShadowModeProcessor(processors=processors))

    def bulkhead(
        self,
        name: str,
        limit: int,
        processors: list[BaseProcessor],
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> "RouteBuilder":
        """Ограничивает concurrency на ветку — защита провайдера от перегрузки."""
        from src.backend.dsl.engine.processors.generic import BulkheadProcessor

        return self._add(
            BulkheadProcessor(
                name=name,
                limit=limit,
                processors=processors,
                wait=wait,
                timeout=timeout,
            )
        )

    def lineage(self, tag: str = "step") -> "RouteBuilder":
        """Записывает шаг в `_lineage` property (data governance)."""
        from src.backend.dsl.engine.processors.generic import LineageTrackerProcessor

        return self._add(LineageTrackerProcessor(tag=tag))

    def ab_test(
        self,
        variant_a: list[BaseProcessor],
        variant_b: list[BaseProcessor],
        *,
        split_percent: int = 50,
        key_fn: Callable[[Exchange[Any]], str] | None = None,
    ) -> "RouteBuilder":
        """Стабильная маршрутизация X% трафика на вариант B."""
        from src.backend.dsl.engine.processors.generic import AbTestRouterProcessor

        return self._add(
            AbTestRouterProcessor(
                variant_a=variant_a,
                variant_b=variant_b,
                split_percent=split_percent,
                key_fn=key_fn,
            )
        )

    def feature_flag_branch(
        self,
        flag: str,
        processors: list[BaseProcessor],
        *,
        resolver: Callable[[str], bool] | None = None,
    ) -> "RouteBuilder":
        """Выполняет ветку процессоров только при включённом feature flag.

        Не путать с ``feature_flag(name)`` (метаданная маршрута, отключает
        маршрут целиком). Здесь — DSL-step внутри pipeline.
        """
        from src.backend.dsl.engine.processors.generic import FeatureFlagGuardProcessor

        return self._add(
            FeatureFlagGuardProcessor(
                flag=flag, processors=processors, resolver=resolver
            )
        )

    # ── Business (W28) ──

    def tenant_scope(
        self,
        *,
        header: str = "x-tenant-id",
        body_path: str | None = None,
        required: bool = True,
    ) -> "RouteBuilder":
        """Multi-tenancy scope: tenant_id из заголовка/body в Exchange."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "TenantScopeProcessor",
            header=header,
            body_path=body_path,
            required=required,
        )

    def cost_tracker(self) -> "RouteBuilder":
        """Инициализация cost-словаря в properties (LLM-токены, HTTP, DB, USD)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business", "CostTrackerProcessor"
        )

    def outbox(self, *, topic: str) -> "RouteBuilder":
        """Transactional Outbox: запись события в outbox-таблицу."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business", "OutboxProcessor", topic=topic
        )

    def mask(
        self, *, patterns: list[str] | None = None, replacement: str = "***"
    ) -> "RouteBuilder":
        """Маскирование PII/PCI в body (ИНН/СНИЛС/карта/email/телефон)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "DataMaskingProcessor",
            patterns=patterns,
            replacement=replacement,
        )

    def compliance_labels(self, *, labels: list[str]) -> "RouteBuilder":
        """Compliance-метки на Exchange (PII/PCI/FIN/GDPR)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "ComplianceLabelProcessor",
            labels=labels,
        )

    # ── Build ──

    def build(self, *, validate_actions: bool = True) -> Pipeline:
        """Собирает Pipeline из накопленных процессоров.

        Финальный вызов в fluent-chain.

        Args:
            validate_actions: Если True (default), проверяет что все
                dispatch_action имена зарегистрированы в ActionHandlerRegistry.
                Raises ValueError с подсказкой схожих имён при опечатке.
        """
        if validate_actions:
            self._validate_action_names()
        return Pipeline(
            route_id=self.route_id,
            source=self.source,
            description=self.description,
            processors=list(self._processors),
            protocol=self._protocol,
            transport_config=self._transport_config,
            feature_flag=self._feature_flag,
        )

    def _validate_action_names(self) -> None:
        """DX-1: проверяет что все dispatch_action имена зарегистрированы.

        Raises ValueError с подсказкой схожих имён при опечатке.
        Вызывается в .build() (можно отключить validate_actions=False).
        """
        try:
            from src.backend.dsl.commands.registry import action_handler_registry

            available = set(action_handler_registry.list_actions())
        except (ImportError, AttributeError):
            return

        if not available:
            return

        action_names: list[str] = []
        for proc in self._processors:
            if type(proc).__name__ == "DispatchActionProcessor":
                action = getattr(proc, "action", None)
                if action and isinstance(action, str):
                    action_names.append(action)

        unknown = [name for name in action_names if name not in available]
        if not unknown:
            return

        import difflib

        suggestions: dict[str, list[str]] = {}
        for name in unknown:
            close = difflib.get_close_matches(name, available, n=3, cutoff=0.6)
            if close:
                suggestions[name] = close

        msg_parts = [f"Unknown action(s) in pipeline '{self.route_id}':"]
        for name in unknown:
            suggestion = suggestions.get(name)
            if suggestion:
                msg_parts.append(
                    f"  - '{name}' — did you mean: {', '.join(suggestion)}?"
                )
            else:
                msg_parts.append(f"  - '{name}'")
        raise ValueError("\n".join(msg_parts))
