"""Core integration / workflow / action / AI / ML миксин для RouteBuilder."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    DispatchActionProcessor,
    PipelineRefProcessor,
)
from src.backend.dsl.engine.processors.invoke import InvokeProcessor


class IntegrationCoreMixin:
    """Поведенческий миксин core integration / workflow / action.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

    def dispatch_action(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Вызывает зарегистрированный action (Service Activator).

        Основной способ связи DSL с бизнес-логикой. Action ищется
        в ActionHandlerRegistry по имени (e.g., "orders.add").
        """
        return self._add(  # type: ignore[attr-defined]
            DispatchActionProcessor(
                action=action,
                payload_factory=payload_factory,
                result_property=result_property,
            )
        )

    def invoke(
        self,
        action: str,
        *,
        mode: str = "sync",
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        reply_channel: str | None = None,
        result_property: str = "invoke_result",
        invocation_id_property: str = "invocation_id",
        timeout: float | None = None,
        correlation_id: str | None = None,
    ) -> RouteBuilder:
        """Вызывает action через :class:`Invoker` (W22) с заданным режимом.

        В отличие от :meth:`dispatch_action`, поддерживает шесть режимов
        (``sync``/``async-api``/``async-queue``/``deferred``/``background``/
        ``streaming``) и возвращает единый ``invocation_id`` для трассировки
        и polling-результата через ReplyChannel registry.

        ``timeout`` ограничивает SYNC-исполнение через ``asyncio.wait_for``;
        ``correlation_id`` — клиентский id для трассировки middleware/reply.
        """
        return self._add(  # type: ignore[attr-defined]
            InvokeProcessor(
                action=action,
                mode=mode,
                payload_factory=payload_factory,
                reply_channel=reply_channel,
                result_property=result_property,
                invocation_id_property=invocation_id_property,
                timeout=timeout,
                correlation_id=correlation_id,
            )
        )

    def to_route(
        self, route_id: str, *, result_property: str = "sub_result"
    ) -> RouteBuilder:
        """Вызов другого зарегистрированного DSL-маршрута."""
        return self._add(  # type: ignore[attr-defined]
            PipelineRefProcessor(route_id=route_id, result_property=result_property)
        )

    def invoke_workflow(
        self,
        name: str,
        *,
        mode: str = "async-api",
        args: dict[str, Any] | None = None,
        namespace: str = "default",
        task_queue: str = "default",
        result_property: str = "workflow_result",
        invocation_id_property: str = "invocation_id",
        reply_timeout_seconds: float = 60.0,
        version: str | None = None,
    ) -> RouteBuilder:
        """Запуск Workflow (Temporal/LiteTemporal/PgRunner) — R-V15-7 / R-V15-9.

        Args:
            name: Логическое имя workflow.
            version: Опциональный SemVer-диапазон (например ``">=1.0,<2.0"``).
                При наличии ``workflow_versioning_routes=True`` — валидируется
                WorkflowLauncher.resolve() при старте workflow.
            mode: Режим вызова:

                * ``"sync"`` — ждёт terminal-статуса (без timeout).
                * ``"async-api"`` — возвращает handle сразу (default).
                * ``"async-reply"`` — fire-and-await с
                  ``reply_timeout_seconds`` timeout (Sprint 8A K3 W11).

            args: Базовые аргументы (если ``None`` — берётся
                ``in_message.body`` если dict).
            namespace: Workflow namespace (Temporal).
            task_queue: Workflow task queue (Temporal).
            result_property: Куда писать результат / handle.
            invocation_id_property: Куда писать workflow_id.
            reply_timeout_seconds: Таймаут для ``async-reply`` (default 60s).
                При timeout result_property получает ``{"status": "timeout",
                "workflow_id": ..., "timeout_seconds": ...}``.
        """
        from src.backend.dsl.engine.processors.invoke_workflow import (
            InvokeWorkflowProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            InvokeWorkflowProcessor(
                name,
                mode=mode,
                args=args,
                namespace=namespace,
                task_queue=task_queue,
                result_property=result_property,
                invocation_id_property=invocation_id_property,
                reply_timeout_seconds=reply_timeout_seconds,
                version=version,
            )
        )

    def cancel_workflow(
        self,
        workflow_id: str,
        *,
        reason: str = "",
        namespace: str = "default",
        result_property: str = "cancel_result",
    ) -> RouteBuilder:
        """Отмена workflow по ``workflow_id`` (Sprint 12 K3 W7).

        Args:
            workflow_id: Литерал или Ref-выражение
                ``"${body.invocation_id}"``.
            reason: Опциональная причина (для audit ``payload.reason``).
            namespace: Workflow namespace (Temporal).
            result_property: Куда писать результат
                (``{"cancelled": True, "workflow_id": ..., "reason": ...}``).
        """
        from src.backend.dsl.engine.processors.cancel_workflow import (
            CancelWorkflowProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CancelWorkflowProcessor(
                workflow_id,
                reason=reason,
                namespace=namespace,
                result_property=result_property,
            )
        )

    def audit(
        self,
        *,
        action: str | None = None,
        action_from: str | None = None,
        actor: str = "system",
        actor_from: str | None = None,
        resource_from: str | None = None,
        outcome: str = "success",
        outcome_from: str | None = None,
        metadata_from: str | None = None,
        tenant_id_from: str | None = None,
        correlation_id_from: str | None = None,
        result_property: str = "audit_event_hash",
    ) -> RouteBuilder:
        """Записать событие в immutable audit log (Wave 5.1)."""
        from src.backend.dsl.engine.processors.audit import AuditProcessor

        return self._add(  # type: ignore[attr-defined]
            AuditProcessor(
                action=action,
                action_from=action_from,
                actor=actor,
                actor_from=actor_from,
                resource_from=resource_from,
                outcome=outcome,
                outcome_from=outcome_from,
                metadata_from=metadata_from,
                tenant_id_from=tenant_id_from,
                correlation_id_from=correlation_id_from,
                result_property=result_property,
            )
        )

    def scan_file(
        self,
        *,
        s3_key_from: str | None = None,
        data_property: str | None = None,
        on_threat: str = "fail",
        result_property: str = "antivirus_scan_result",
    ) -> RouteBuilder:
        """Сканировать файл AV-бэкендом (Wave 2.4)."""
        from src.backend.dsl.engine.processors.scan_file import ScanFileProcessor

        return self._add(  # type: ignore[attr-defined]
            ScanFileProcessor(
                s3_key_from=s3_key_from,
                data_property=data_property,
                on_threat=on_threat,
                result_property=result_property,
            )
        )

    def call_function(
        self,
        ref: str,
        *,
        payload_from: str = "body",
        result_property: str = "function_result",
        inject: list[str] | None = None,
    ) -> RouteBuilder:
        """Вызов Python-функции ``module:fn`` (R-V15-6, V21 security).

        Безопасность: module-whitelist через
        ``plugin.toml::call_function_modules`` + capability
        ``function.call.<module>`` + audit-log каждого вызова.
        См. :class:`CallFunctionProcessor`.

        Args:
            ref: ``module.path:fn_name``.
            payload_from: ``body`` | ``body.<field>`` | ``properties.<name>``.
            result_property: Имя property для результата.
        """
        from src.backend.dsl.engine.processors.function_call import (
            CallFunctionProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CallFunctionProcessor(
                ref=ref,
                payload_from=payload_from,
                result_property=result_property,
                inject=inject,
            )
        )

    def get_setting(
        self, path: str, *, to: str = "body.setting", default: Any = None
    ) -> RouteBuilder:
        """Чтение настройки из application config (R-V15-17).

        Capability ``settings.read.<scope>``. См. :class:`GetSettingProcessor`.

        Args:
            path: Точечный путь (``skb.api_url``, ``ai.openai.model``).
            to: ``body.<field>`` | ``properties.<name>``.
            default: Значение по умолчанию если путь отсутствует.
        """
        from src.backend.dsl.engine.processors.get_setting import GetSettingProcessor

        return self._add(  # type: ignore[attr-defined]
            GetSettingProcessor(path=path, to=to, default=default)
        )

    def validate_response(
        self,
        *,
        schema: type | str | None = None,
        on_error: str = "fail",
        source: str = "out_body",
    ) -> RouteBuilder:
        """Pydantic-валидация response_body (R-V15-18).

        См. :class:`ResponseValidatorProcessor`.

        Args:
            schema: Pydantic-модель (тип) или ``module:ClassName`` (str для
                YAML-loader).
            on_error: ``fail`` | ``dlq`` | ``warn``.
            source: ``out_body`` (default) | ``in_body``.
        """
        from src.backend.dsl.engine.processors.validate_response import (
            ResponseValidatorProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ResponseValidatorProcessor(schema=schema, on_error=on_error, source=source)
        )

    def render_docx(
        self,
        *,
        template: str,
        context_from: str | None = None,
        output_to: str = "docx_path",
    ) -> RouteBuilder:
        """Рендерит шаблон ``.docx`` со встроенными плейсхолдерами ``{{key}}``.

        Wave: ``[wave:s5/doc-generation-dsl]``. Использует python-docx
        (уже в зависимостях), без добавления docxtpl.

        Args:
            template: Путь к шаблону ``.docx``.
            context_from: dotted-path в ``exchange.body`` к словарю
                подстановок. ``None`` — весь body.
            output_to: dotted-path для записи пути созданного файла.
        """
        from src.backend.dsl.engine.processors.documents import (
            RenderDocxParams,
            RenderDocxProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            RenderDocxProcessor(
                RenderDocxParams(
                    template=template, context_from=context_from, output_to=output_to
                )
            )
        )

    def render_xlsx(
        self,
        *,
        template: str | None = None,
        context_from: str | None = None,
        output_to: str = "xlsx_path",
        mode: str = "replace",
    ) -> RouteBuilder:
        """Рендерит ``.xlsx`` (``replace`` placeholders или ``append_table``).

        Wave: ``[wave:s5/doc-generation-dsl]``. Использует openpyxl
        (уже в зависимостях), без добавления xlsxwriter.

        Args:
            template: Путь к существующему ``.xlsx`` (``None`` — новая книга).
            context_from: dotted-path к данным (dict или list[dict]).
            output_to: dotted-path для пути результата.
            mode: ``replace`` — подстановка ``{{key}}``; ``append_table`` —
                добавление list[dict] как таблицы.
        """
        from src.backend.dsl.engine.processors.documents import (
            RenderXlsxParams,
            RenderXlsxProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            RenderXlsxProcessor(
                RenderXlsxParams(
                    template=template,
                    context_from=context_from,
                    output_to=output_to,
                    mode=mode,
                )
            )
        )

    def evaluate_rules(
        self,
        *,
        rules: list[Any],
        context_from: str | None = None,
        decision_to: str = "decision",
        default_decision: str = "NO_MATCH",
    ) -> RouteBuilder:
        """First-match-wins rule engine поверх SimpleEval.

        Wave: ``[wave:s8/rule-engine-scaffold]``. Безопасный
        синхронный evaluator (без import/exec/eval-доступа к dunder'ам).

        Args:
            rules: Список ``Rule`` или dict с полями ``name``/``expr``/``decision``.
            context_from: dotted-path к словарю переменных.
            decision_to: dotted-path для записи решения.
            default_decision: Значение, если ни одно правило не сработало.
        """
        from src.backend.dsl.engine.processors.rule_engine import (
            EvaluateRulesParams,
            EvaluateRulesProcessor,
            Rule,
        )

        normalized: list[Rule] = [
            r if isinstance(r, Rule) else Rule(**r) for r in rules
        ]
        return self._add(  # type: ignore[attr-defined]
            EvaluateRulesProcessor(
                EvaluateRulesParams(
                    rules=normalized,
                    context_from=context_from,
                    decision_to=decision_to,
                    default_decision=default_decision,
                )
            )
        )

    def llm_structured(
        self,
        *,
        model: str,
        output_schema: Any,
        prompt: str,
        retry: int = 3,
        temperature: float = 0.0,
        cost_budget_usd: float | None = None,
        to: str = "body.llm_result",
        name: str | None = None,
    ) -> RouteBuilder:
        """LLM-вызов с гарантированным Pydantic-объектом.

        Wave: ``[wave:s8/k4-llm-structured-finale]``. Обёртка над
        :class:`LLMStructuredProcessor` (instructor + litellm). Поддержка
        outer retry на network errors (через ``make_async_retry``) и
        inner — instructor ``max_retries`` для Pydantic-валидации.

        Args:
            model: Идентификатор в формате ``<provider>/<model>``
                (``anthropic/claude-sonnet-4-6``, ``openai/gpt-4o``).
            output_schema: ``type[BaseModel]`` или ``"module:Class"`` /
                имя класса в ``ServiceSchemaRegistry``.
            prompt: Шаблон промпта; ``${body.x}`` / ``${properties.y}``
                подставляются из exchange.
            retry: instructor inner ``max_retries`` (Pydantic-валидация).
            temperature: Sampling-temperature; для structured output
                0.0 (детерминизм) по умолчанию.
            cost_budget_usd: Опц. бюджет; превышение → ``exchange.fail``.
            to: Путь записи результата (``body.<field>`` / ``body`` /
                ``property:<name>``).
            name: Имя процессора в трейсах/метриках.
        """
        from src.backend.dsl.engine.processors.llm_structured import (
            LLMStructuredProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            LLMStructuredProcessor(
                model=model,
                output_schema=output_schema,
                prompt=prompt,
                retry=retry,
                temperature=temperature,
                cost_budget_usd=cost_budget_usd,
                to=to,
                name=name,
            )
        )

    def ml_predict(
        self,
        model: str,
        *,
        input_field: str = "body.features",
        output_property: str = "ml_prediction",
        model_type: str | None = None,
        name: str | None = None,
    ) -> RouteBuilder:
        """Выполняет ML-инференс через локальный filesystem model registry.

        Wave: ``[wave:s29/local-models-repository]``. Использует
        :class:`MLPredictProcessor` + :class:`MLModelLoader`.

        Модель ищется в ``${AI_WORKSPACE}/models/<model>/`` через
        :class:`LocalFSModelRegistry`. Поддерживает torch, onnx, sklearn,
        catboost, lightgbm.

        Args:
            model: Имя модели в LocalFSModelRegistry.
            input_field: dotted-path к входным данным (default ``body.features``).
            output_property: Куда положить результат инференса.
            model_type: Явный тип модели (default — по расширению файла).
            name: Имя процессора в трейсах.
        """
        from src.backend.dsl.engine.processors.ml_predict import MLPredictProcessor

        return self._add(  # type: ignore[attr-defined]
            MLPredictProcessor(
                model_endpoint=model,
                input_field=input_field,
                output_property=output_property,
                model_type=model_type,
                name=name,
            )
        )
