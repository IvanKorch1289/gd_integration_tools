"""Integration / Transport / Storage / Security миксин для RouteBuilder.

Группа: dispatch_action / invoke / auth / to_route /
expose_proxy / forward_to / proxy / redirect /
entity_create / entity_get / entity_update / entity_delete / entity_list /
crud_create / crud_read / crud_update / crud_delete / crud_list /
audit / scan_file / http_call / db_query / db_query_external /
read_file / write_file / read_s3 / write_s3 / file_move / timer / poll /
notify / shell / email /
require_header / require_bearer / require_auth / require_fields /
jwt_sign / jwt_verify / webhook_sign / webhook_verify / deadline +
NEW invoke_workflow / call_function / get_setting / validate_response.

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    BaseProcessor,
    CallableProcessor,
    DispatchActionProcessor,
    PipelineRefProcessor,
)
from src.backend.dsl.engine.processors.invoke import InvokeProcessor

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class IntegrationMixin:
    """Поведенческий миксин integration / transport / storage / security.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

    # ── Service Activator / Workflow вызовы ──

    def dispatch_action(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Вызывает зарегистрированный action (Service Activator).

        Основной способ связи DSL с бизнес-логикой. Action ищется
        в ActionHandlerRegistry по имени (e.g., "orders.add").
        """
        return self._add(  # type: ignore[attr-defined,no-any-return]
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
    ) -> "RouteBuilder":
        """Вызывает action через :class:`Invoker` (W22) с заданным режимом.

        В отличие от :meth:`dispatch_action`, поддерживает шесть режимов
        (``sync``/``async-api``/``async-queue``/``deferred``/``background``/
        ``streaming``) и возвращает единый ``invocation_id`` для трассировки
        и polling-результата через ReplyChannel registry.

        ``timeout`` ограничивает SYNC-исполнение через ``asyncio.wait_for``;
        ``correlation_id`` — клиентский id для трассировки middleware/reply.
        """
        return self._add(  # type: ignore[attr-defined,no-any-return]
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
    ) -> "RouteBuilder":
        """Вызов другого зарегистрированного DSL-маршрута."""
        return self._add(  # type: ignore[attr-defined,no-any-return]
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
    ) -> "RouteBuilder":
        """Запуск Workflow (Temporal/LiteTemporal/PgRunner) — R-V15-7 / R-V15-9.

        Args:
            name: Логическое имя workflow.
            mode: ``"sync"`` ждёт terminal-статуса, ``"async-api"``
                возвращает handle сразу (default).
            args: Базовые аргументы (если ``None`` — берётся
                ``in_message.body`` если dict).
            namespace: Workflow namespace (Temporal).
            task_queue: Workflow task queue (Temporal).
            result_property: Куда писать результат / handle.
            invocation_id_property: Куда писать workflow_id.
        """
        from src.backend.dsl.engine.processors.invoke_workflow import (
            InvokeWorkflowProcessor,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            InvokeWorkflowProcessor(
                name,
                mode=mode,
                args=args,
                namespace=namespace,
                task_queue=task_queue,
                result_property=result_property,
                invocation_id_property=invocation_id_property,
            )
        )

    # ── Auth (Wave 8.1) ──

    def auth(
        self,
        methods: list[str] | str = "api_key",
        *,
        result_property: str = "auth",
        required: bool = True,
    ) -> "RouteBuilder":
        """Проверяет авторизацию запроса (Wave 8.1).

        Args:
            methods: Один или список разрешённых AuthMethod
                (``api_key`` / ``jwt`` / ``express_jwt`` / ``mtls`` / ``basic``).
            result_property: Имя property для AuthContext.
            required: Если True — при провале маршрут останавливается.
        """
        from src.backend.dsl.engine.processors.security import AuthValidateProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
            AuthValidateProcessor(
                methods=methods, result_property=result_property, required=required
            )
        )

    # ── Proxy pass-through (Wave 3.5 / ADR-014) ──

    def expose_proxy(
        self,
        src: str,
        *,
        methods: list[str] | None = None,
        header_map: dict[str, Any] | None = None,
    ) -> "RouteBuilder":
        """Объявить роут как прокси-вход.

        Args:
            src: ``<protocol>:<address>`` (``http:/api/payments``,
                ``kafka:orders.in`` и т.п.).
            methods: HTTP-методы (для ``http``). ``None`` = все.
            header_map: Опциональный словарь ``{add|drop|override}`` для
                политики inbound-headers.
        """
        from src.backend.dsl.engine.processors.proxy import (
            ExposeProxyProcessor,
            HeaderMapPolicy,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            ExposeProxyProcessor(
                src=src,
                methods=methods,
                header_policy=HeaderMapPolicy.from_dict(header_map),
            )
        )

    def forward_to(
        self,
        dst: str,
        *,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> "RouteBuilder":
        """Переслать текущее сообщение в backend без трансформаций."""
        from src.backend.dsl.engine.processors.proxy import (
            ForwardToProcessor,
            HeaderMapPolicy,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            ForwardToProcessor(
                dst=dst,
                pass_headers=pass_headers,
                header_policy=HeaderMapPolicy.from_dict(header_map),
                rewrite_path=rewrite_path,
                timeout=timeout,
            )
        )

    def proxy(
        self,
        src: str,
        dst: str,
        *,
        methods: list[str] | None = None,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> "RouteBuilder":
        """Сокращение: ``expose_proxy(src) → forward_to(dst)``."""
        return self.expose_proxy(  # type: ignore[attr-defined,no-any-return]
            src=src, methods=methods, header_map=header_map
        ).forward_to(
            dst=dst,
            pass_headers=pass_headers,
            header_map=header_map,
            rewrite_path=rewrite_path,
            timeout=timeout,
        )

    def redirect(
        self,
        target_url: str | None = None,
        *,
        status_code: int = 302,
        url_source: str | None = None,
        source_key: str | None = None,
        allowed_hosts: list[str] | None = None,
    ) -> "RouteBuilder":
        """Добавляет HTTP-redirect в маршрут.

        Args:
            target_url: Фиксированный URL назначения (``mode=static``).
                Если задан — используется static-режим.
            status_code: HTTP-статус редиректа (301/302/307/308). По умолчанию 302.
            url_source: Источник URL для proxy-режима:
                ``header`` | ``body_field`` | ``exchange_var`` | ``query_param``.
            source_key: Ключ для извлечения URL из источника.
            allowed_hosts: Белый список хостов (для ``url_source=query_param``).
        """
        from src.backend.dsl.engine.processors.proxy import RedirectProcessor

        if target_url is not None:
            return self._add(  # type: ignore[attr-defined,no-any-return]
                RedirectProcessor(
                    mode="static", status_code=status_code, target_url=target_url
                )
            )
        return self._add(  # type: ignore[attr-defined,no-any-return]
            RedirectProcessor(
                mode="proxy",
                status_code=status_code,
                url_source=url_source,
                source_key=source_key,
                allowed_hosts=allowed_hosts,
            )
        )

    # ── Entity CRUD (Wave 11) ──

    def entity_create(
        self,
        *,
        entity: str,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Создать сущность через action ``<entity>.create``."""
        from src.backend.dsl.engine.processors.entity import EntityCreateProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
            EntityCreateProcessor(
                entity=entity,
                payload_from=payload_from,
                result_property=result_property,
            )
        )

    def entity_get(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Прочитать сущность через action ``<entity>.get``."""
        from src.backend.dsl.engine.processors.entity import EntityGetProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
            EntityGetProcessor(
                entity=entity, id_from=id_from, result_property=result_property
            )
        )

    def entity_update(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Обновить сущность через action ``<entity>.update``."""
        from src.backend.dsl.engine.processors.entity import EntityUpdateProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
            EntityUpdateProcessor(
                entity=entity,
                id_from=id_from,
                payload_from=payload_from,
                result_property=result_property,
            )
        )

    def entity_delete(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Удалить сущность через action ``<entity>.delete``."""
        from src.backend.dsl.engine.processors.entity import EntityDeleteProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
            EntityDeleteProcessor(
                entity=entity, id_from=id_from, result_property=result_property
            )
        )

    def entity_list(
        self,
        *,
        entity: str,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        page_from: str | None = None,
        size_from: str | None = None,
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Получить страницу сущностей через action ``<entity>.list``."""
        from src.backend.dsl.engine.processors.entity import EntityListProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
            EntityListProcessor(
                entity=entity,
                filters_from=filters_from,
                page=page,
                size=size,
                page_from=page_from,
                size_from=size_from,
                result_property=result_property,
            )
        )

    # ── CRUD aliases (R-V15-12) ──

    def crud_create(
        self,
        entity: str,
        *,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Алиас к :meth:`entity_create` (R-V15-12 / 80/20 YAML)."""
        return self.entity_create(
            entity=entity,
            payload_from=payload_from,
            result_property=result_property,
        )

    def crud_read(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Алиас к :meth:`entity_get` (R-V15-12)."""
        return self.entity_get(
            entity=entity, id_from=id_from, result_property=result_property
        )

    def crud_update(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Алиас к :meth:`entity_update` (R-V15-12)."""
        return self.entity_update(
            entity=entity,
            id_from=id_from,
            payload_from=payload_from,
            result_property=result_property,
        )

    def crud_delete(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Алиас к :meth:`entity_delete` (R-V15-12)."""
        return self.entity_delete(
            entity=entity, id_from=id_from, result_property=result_property
        )

    def crud_list(
        self,
        entity: str,
        *,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Алиас к :meth:`entity_list` (R-V15-12)."""
        return self.entity_list(
            entity=entity,
            filters_from=filters_from,
            page=page,
            size=size,
            result_property=result_property,
        )

    # ── Audit + Antivirus ──

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
    ) -> "RouteBuilder":
        """Записать событие в immutable audit log (Wave 5.1)."""
        from src.backend.dsl.engine.processors.audit import AuditProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
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
    ) -> "RouteBuilder":
        """Сканировать файл AV-бэкендом (Wave 2.4)."""
        from src.backend.dsl.engine.processors.scan_file import ScanFileProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
            ScanFileProcessor(
                s3_key_from=s3_key_from,
                data_property=data_property,
                on_threat=on_threat,
                result_property=result_property,
            )
        )

    # ── HTTP / DB / file / S3 / timer / poll ──

    def http_call(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> "RouteBuilder":
        """HTTP client: GET/POST/PUT/DELETE с таймаутом и headers."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.components",
            "HttpCallProcessor",
            url=url,
            method=method,
            headers=headers,
            auth_token=auth_token,
            timeout=timeout,
            result_property=result_property,
        )

    def db_query(
        self, sql: str, *, result_property: str = "db_result"
    ) -> "RouteBuilder":
        """SQL-запрос через SQLAlchemy (с валидацией: DDL/multi-statement запрещены)."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.components",
            "DatabaseQueryProcessor",
            sql=sql,
            result_property=result_property,
        )

    def read_file(
        self, path: str | None = None, *, binary: bool = False
    ) -> "RouteBuilder":
        """Чтение локального файла в body (text или bytes)."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.components",
            "FileReadProcessor",
            path=path,
            binary=binary,
        )

    def write_file(
        self, path: str | None = None, *, format: str = "auto"
    ) -> "RouteBuilder":
        """Запись body в файл. format: auto|json|csv|text."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.components",
            "FileWriteProcessor",
            path=path,
            format=format,
        )

    def read_s3(
        self, bucket: str | None = None, key: str | None = None
    ) -> "RouteBuilder":
        """Загрузка объекта из S3."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.components",
            "S3ReadProcessor",
            bucket=bucket,
            key=key,
        )

    def write_s3(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        content_type: str = "application/octet-stream",
    ) -> "RouteBuilder":
        """Выгрузка body в S3."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.components",
            "S3WriteProcessor",
            bucket=bucket,
            key=key,
            content_type=content_type,
        )

    def timer(
        self,
        *,
        interval_seconds: float | None = None,
        cron: str | None = None,
        max_fires: int | None = None,
    ) -> "RouteBuilder":
        """Scheduled event source: интервал или cron-выражение."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.components",
            "TimerProcessor",
            interval_seconds=interval_seconds,
            cron=cron,
            max_fires=max_fires,
        )

    def poll(
        self,
        source_action: str,
        *,
        payload: dict[str, Any] | None = None,
        result_property: str = "polled_data",
    ) -> "RouteBuilder":
        """Periodically вызывает action, результат → body."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.components",
            "PollingConsumerProcessor",
            source_action=source_action,
            payload=payload,
            result_property=result_property,
        )

    def db_query_external(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = "body",
        result_property: str = "db_result",
        fetch: str = "all",
        commit: bool = False,
    ) -> "RouteBuilder":
        """Выполняет произвольный SQL во внешней БД по profile-имени.

        Использует ``ExternalDatabaseRegistry`` (через DI) для получения
        async-сессии. Параметры берутся из body / properties / headers.
        """
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.db_query_external",
            "ExternalDbQueryProcessor",
            profile=profile,
            sql=sql,
            params_from=params_from,
            result_property=result_property,
            fetch=fetch,
            commit=commit,
        )

    # ── Notify / shell / email / file_move ──

    def notify(
        self,
        channel: str = "email",
        *,
        template_key: str = "default",
        recipient: str | None = None,
        priority: str = "tx",
        locale: str = "ru",
        context_property: str | None = None,
        result_property: str = "notify_result",
    ) -> "RouteBuilder":
        """Отправка уведомления через NotificationGateway (Wave 8.3).

        Args:
            channel: ``email|sms|slack|teams|telegram|webhook|express``.
            template_key: Имя шаблона в TemplateRegistry.
            recipient: Получатель. Если None — берётся из ``body['recipient']``.
            priority: ``tx`` или ``marketing``.
            locale: Локаль шаблона.
            context_property: Имя property с контекстом для рендера.
            result_property: Имя property для ``SendResult``.
        """
        from src.backend.dsl.engine.processors.notify import NotifyProcessor

        return self._add(  # type: ignore[attr-defined,no-any-return]
            NotifyProcessor(
                channel=channel,
                template_key=template_key,
                recipient=recipient,
                priority=priority,
                locale=locale,
                context_property=context_property,
                result_property=result_property,
            )
        )

    def notify_apprise(
        self,
        channel: str,
        title: str,
        body: str,
        *,
        body_format: str = "text",
        result_property: str = "notify_apprise_result",
    ) -> "RouteBuilder":
        """Отправка уведомления через Apprise (S3 K3 W1, 100+ backends).

        Делегирует в :class:`AppriseNotifyProcessor`, который использует
        :class:`~src.backend.services.notifications.AppriseNotificationService`.

        Требует ``feature_flags.notification_dsl_enabled = True`` и
        зарегистрированного канала через
        :meth:`~AppriseNotificationService.register_channel`.

        Args:
            channel: Имя зарегистрированного Apprise-канала (e.g. ``"slack"``).
            title: Заголовок уведомления.
            body: Тело уведомления.
            body_format: Формат тела: ``text`` | ``html`` | ``markdown``.
            result_property: Имя property для результата (``True``/``False``).
        """
        from src.backend.dsl.engine.processors.notify.apprise_notify import (
            AppriseNotifyProcessor,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            AppriseNotifyProcessor(
                channel=channel,
                title=title,
                body=body,
                body_format=body_format,
                result_property=result_property,
            )
        )

    def notify_multi(
        self,
        channels: list[str],
        title: str,
        body: str,
        *,
        body_format: str = "text",
        result_property: str = "notify_multi_result",
    ) -> "RouteBuilder":
        """Отправка уведомления в несколько Apprise-каналов одновременно (S3 K3 W1).

        Использует :meth:`~AppriseNotificationService.notify_multi` для
        параллельной доставки. Результат — словарь ``{channel: bool}``
        с итогом для каждого канала.

        Args:
            channels: Список имён зарегистрированных каналов.
            title: Заголовок уведомления.
            body: Тело уведомления.
            body_format: Формат тела: ``text`` | ``html`` | ``markdown``.
            result_property: Имя property для словаря результатов.
        """
        from src.backend.dsl.engine.processors.base import CallableProcessor

        async def _send_multi(exch: "Exchange[Any]", ctx: object) -> None:
            from src.backend.services.notifications.apprise_service import (
                get_notification_service,
            )

            svc = get_notification_service()
            results = await svc.notify_multi(
                channels=channels,
                title=title,
                body=body,
                body_format=body_format,  # type: ignore[arg-type]
            )
            exch.set_property(result_property, results)

        return self._add(  # type: ignore[attr-defined,no-any-return]
            CallableProcessor(_send_multi, name=f"notify_multi:{','.join(channels)}")
        )

    def file_move(
        self, src: str | None = None, dst: str | None = None, *, mode: str = "copy"
    ) -> "RouteBuilder":
        """Copy/move/rename файлов."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.rpa",
            "FileMoveProcessor",
            src=src,
            dst=dst,
            mode=mode,
        )

    def shell(
        self,
        command: str,
        *,
        args: list[str] | None = None,
        allowed_commands: list[str] | None = None,
    ) -> "RouteBuilder":
        """Shell-команда с whitelist и timeout."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.rpa",
            "ShellExecProcessor",
            command=command,
            args=args,
            allowed_commands=allowed_commands,
        )

    def email(self, to: str, subject: str, body_template: str) -> "RouteBuilder":
        """Compose + send email через SMTP."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.rpa",
            "EmailComposeProcessor",
            to=to,
            subject=subject,
            body_template=body_template,
        )

    # ── DSL v3: .require_* helpers ──

    def require_header(self, name: str) -> "RouteBuilder":
        """DX-2: валидирует присутствие header. Fail route если отсутствует.

        Usage::
            .require_header("Authorization")
        """

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            if not exchange.in_message.headers.get(name):
                exchange.fail(f"Missing required header: {name}")

        return self._add(  # type: ignore[attr-defined,no-any-return]
            CallableProcessor(_check, name=f"require_header:{name}")
        )

    def require_bearer(self) -> "RouteBuilder":
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

        return self._add(  # type: ignore[attr-defined,no-any-return]
            CallableProcessor(_check, name="require_bearer")
        )

    def require_auth(self) -> "RouteBuilder":
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

        return self._add(  # type: ignore[attr-defined,no-any-return]
            CallableProcessor(_check, name="require_auth")
        )

    def require_fields(self, *names: str) -> "RouteBuilder":
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

        return self._add(  # type: ignore[attr-defined,no-any-return]
            CallableProcessor(_check, name=f"require_fields:{','.join(required)}")
        )

    # ── JWT / Webhook sign/verify + deadline (enrichment) ──

    def jwt_sign(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        expires_in_seconds: int | None = 3600,
        output_property: str = "jwt",
    ) -> "RouteBuilder":
        """Подпись payload как JWT-токен (PyJWT)."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
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
    ) -> "RouteBuilder":
        """Проверка JWT из заголовка; claims → property или fail."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
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
    ) -> "RouteBuilder":
        """HMAC-подпись outgoing webhook'а."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
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
    ) -> "RouteBuilder":
        """Верификация HMAC-подписи входящего webhook'а (timing-safe).

        ``on_mismatch="fail"`` (default) — fail pipeline; ``"warn"`` — лог
        предупреждения и установка ``webhook_signature_valid=False`` без
        остановки. ``prefix`` — опциональный схема-префикс (``"v1"``,
        ``"sha256"``), если подпись передаётся как ``v1=<hex>``.
        """
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.enrichment",
            "WebhookSignVerifyProcessor",
            secret=secret,
            header=header,
            algorithm=algorithm,
            prefix=prefix,
            on_mismatch=on_mismatch,
        )

    def deadline(
        self, *, timeout_seconds: float = 30.0, fail_on_exceed: bool = True
    ) -> "RouteBuilder":
        """Установка дedline pipeline; downstream проверяет _deadline_at."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.enrichment",
            "DeadlineProcessor",
            timeout_seconds=timeout_seconds,
            fail_on_exceed=fail_on_exceed,
        )

    # ── 80/20 YAML — call_function / get_setting / validate_response ──

    def call_function(
        self,
        ref: str,
        *,
        payload_from: str = "body",
        result_property: str = "function_result",
    ) -> "RouteBuilder":
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

        return self._add(  # type: ignore[attr-defined,no-any-return]
            CallFunctionProcessor(
                ref=ref,
                payload_from=payload_from,
                result_property=result_property,
            )
        )

    def get_setting(
        self,
        path: str,
        *,
        to: str = "body.setting",
        default: Any = None,
    ) -> "RouteBuilder":
        """Чтение настройки из application config (R-V15-17).

        Capability ``settings.read.<scope>``. См. :class:`GetSettingProcessor`.

        Args:
            path: Точечный путь (``skb.api_url``, ``ai.openai.model``).
            to: ``body.<field>`` | ``properties.<name>``.
            default: Значение по умолчанию если путь отсутствует.
        """
        from src.backend.dsl.engine.processors.get_setting import (
            GetSettingProcessor,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            GetSettingProcessor(path=path, to=to, default=default)
        )

    def validate_response(
        self,
        *,
        schema: type | str | None = None,
        on_error: str = "fail",
        source: str = "out_body",
    ) -> "RouteBuilder":
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

        return self._add(  # type: ignore[attr-defined,no-any-return]
            ResponseValidatorProcessor(
                schema=schema, on_error=on_error, source=source
            )
        )

    # ── Sink fluent API (Sprint 3 W1 K3 — 10 .sink_*() методов) ──

    def sink_grpc(
        self,
        *,
        target: str,
        full_method: str,
        secure: bool = True,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "grpc_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для gRPC unary-вызова (Sprint 3 W1 K3).

        Тонкий wrapper над :class:`GrpcCallProcessor` — публикует
        payload через :class:`~src.backend.infrastructure.sinks.grpc_sink.GrpcSink`.

        Args:
            target: ``host:port`` целевого сервера.
            full_method: Fully-qualified ``"/package.Service/Method"``.
            secure: Использовать TLS (default True).
            timeout: Дедлайн вызова в секундах.
            payload_property: Имя property с payload (None → ``in_message.body``).
            result_property: Имя property для результата публикации.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GrpcCallProcessor,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            GrpcCallProcessor(
                target=target,
                full_method=full_method,
                secure=secure,
                timeout=timeout,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_soap(
        self,
        *,
        wsdl_url: str,
        operation: str,
        service_name: str | None = None,
        port_name: str | None = None,
        timeout: float = 30.0,
        payload_property: str | None = None,
        result_property: str = "soap_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для SOAP/WSDL-вызова (Sprint 3 W1 K3).

        См. :class:`SoapCallProcessor` и
        :class:`~src.backend.infrastructure.sinks.soap_sink.SoapSink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            SoapCallProcessor,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            SoapCallProcessor(
                wsdl_url=wsdl_url,
                operation=operation,
                service_name=service_name,
                port_name=port_name,
                timeout=timeout,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_mq(
        self,
        *,
        broker: str,
        url: str,
        topic: str,
        extra: dict[str, Any] | None = None,
        payload_property: str | None = None,
        result_property: str = "mq_publish_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для публикации в Kafka/RabbitMQ/Redis-Streams/NATS.

        См. :class:`MqPublishProcessor` и
        :class:`~src.backend.infrastructure.sinks.mq_sink.MqSink`.

        Args:
            broker: ``"kafka"`` | ``"rabbit"`` | ``"redis"`` | ``"nats"``.
            url: Broker URL.
            topic: Топик / exchange / stream / subject.
            extra: Доп. параметры publish (routing_key, partition, headers).
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            MqPublishProcessor,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            MqPublishProcessor(
                broker=broker,
                url=url,
                topic=topic,
                extra=extra,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_ws(
        self,
        *,
        url: str,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "ws_publish_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для outbound WebSocket publish.

        См. :class:`WsPublishProcessor` и
        :class:`~src.backend.infrastructure.sinks.ws_sink.WsSink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            WsPublishProcessor,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            WsPublishProcessor(
                url=url,
                extra_headers=extra_headers,
                timeout=timeout,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_mqtt(
        self,
        *,
        host: str,
        topic: str,
        port: int = 1883,
        qos: int = 0,
        retain: bool = False,
        username: str | None = None,
        password: str | None = None,
        payload_property: str | None = None,
        result_property: str = "mqtt_publish_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для публикации в MQTT-брокер.

        См. :class:`MqttPublishProcessor` и
        :class:`~src.backend.infrastructure.sinks.mqtt_sink.MqttSink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            MqttPublishProcessor,
        )

        return self._add(  # type: ignore[attr-defined,no-any-return]
            MqttPublishProcessor(
                host=host,
                topic=topic,
                port=port,
                qos=qos,
                retain=retain,
                username=username,
                password=password,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_email(
        self,
        *,
        host: str,
        from_addr: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
        start_tls: bool = True,
        default_to: str | None = None,
        default_subject: str = "",
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для SMTP-публикации (Sprint 3 W1 K3).

        Использует обобщённый :class:`GenericSinkPublishProcessor` —
        строит :class:`~src.backend.infrastructure.sinks.email_sink.EmailSink`
        через :func:`build_sink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {
            "host": host,
            "port": port,
            "from_addr": from_addr,
            "use_tls": use_tls,
            "start_tls": start_tls,
            "default_subject": default_subject,
        }
        if username is not None:
            config["username"] = username
        if password is not None:
            config["password"] = password
        if default_to is not None:
            config["default_to"] = default_to

        return self._add(  # type: ignore[attr-defined,no-any-return]
            GenericSinkPublishProcessor(
                kind="email",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_webhook(
        self,
        *,
        url: str,
        event: str,
        secret: str | None = None,
        timeout: float = 10.0,
        extra_headers: dict[str, str] | None = None,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для outbound webhook с HMAC-подписью.

        См. :class:`~src.backend.infrastructure.sinks.webhook_sink.WebhookSink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {
            "url": url,
            "event": event,
            "timeout": timeout,
        }
        if secret is not None:
            config["secret"] = secret
        if extra_headers:
            config["extra_headers"] = dict(extra_headers)

        return self._add(  # type: ignore[attr-defined,no-any-return]
            GenericSinkPublishProcessor(
                kind="webhook",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_file(
        self,
        *,
        path: str,
        mode: str = "append",
        encoding: str = "utf-8",
        ensure_dir: bool = True,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для записи в local FS (append / write).

        См. :class:`~src.backend.infrastructure.sinks.file_sink.FileSink`.

        Args:
            path: Целевой путь к файлу.
            mode: ``"append"`` (NDJSON) или ``"write"`` (атомарный rewrite).
            encoding: Кодировка для текстовых payload (UTF-8 default).
            ensure_dir: Создавать parent dir если отсутствует.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {
            "path": path,
            "mode": mode,
            "encoding": encoding,
            "ensure_dir": ensure_dir,
        }

        return self._add(  # type: ignore[attr-defined,no-any-return]
            GenericSinkPublishProcessor(
                kind="file",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_http(
        self,
        *,
        url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для REST POST/PUT/PATCH/DELETE через Sink.

        В отличие от :meth:`http_call` (general-purpose HTTP client),
        :meth:`sink_http` использует
        :class:`~src.backend.infrastructure.sinks.http_sink.HttpSink` для
        полной Sink-симметрии (один обобщённый ``sink_publish`` step).
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {
            "url": url,
            "method": method,
            "timeout": timeout,
        }
        if headers:
            config["headers"] = dict(headers)

        return self._add(  # type: ignore[attr-defined,no-any-return]
            GenericSinkPublishProcessor(
                kind="http",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_s3(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> "RouteBuilder":
        """Camel-style fluent для выгрузки payload в S3/MinIO.

        См. :class:`~src.backend.infrastructure.sinks.s3_sink.S3Sink`
        (Sprint 3 W1 K3, GAP-03 symmetry).
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {
            "bucket": bucket,
            "key": key,
            "content_type": content_type,
        }

        return self._add(  # type: ignore[attr-defined,no-any-return]
            GenericSinkPublishProcessor(
                kind="s3",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )
