from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.logging.factory import get_logger

app_logger = get_logger("application")

from src.backend.plugins.composition.lifecycle.bootstrap import (  # noqa: E402
    bootstrap_resilience_coordinator as _bootstrap_resilience_coordinator,
)
from src.backend.plugins.composition.lifecycle.bootstrap import (  # noqa: E402
    bootstrap_snapshot_job as _bootstrap_snapshot_job,
)
from src.backend.plugins.composition.lifecycle.bootstrap import (  # noqa: E402
    register_storage_singletons as _register_storage_singletons,
)
from src.backend.plugins.composition.lifecycle.bootstrap import (  # noqa: E402
    validate_cache_layers as _validate_cache_layers,
)
from src.backend.plugins.composition.lifecycle.protocols import (  # noqa: E402
    register_protocol_providers as _register_protocol_providers,
)
from src.backend.plugins.composition.lifecycle.v11 import (  # noqa: E402
    bootstrap_v11_plugin_loader as _bootstrap_v11_plugin_loader,
)
from src.backend.plugins.composition.lifecycle.v11 import (  # noqa: E402
    bootstrap_v11_route_loader as _bootstrap_v11_route_loader,
)
from src.backend.plugins.composition.lifecycle.v11 import (  # noqa: E402
    shutdown_v11_loaders as _shutdown_v11_loaders,
)
from src.backend.plugins.composition.lifecycle.v11 import (  # noqa: E402
    start_v11_hot_reload as _start_v11_hot_reload,
)
from src.backend.plugins.composition.lifecycle.watchers import (  # noqa: E402
    start_dsl_yaml_watcher as _start_dsl_yaml_watcher,
)
from src.backend.plugins.composition.lifecycle.watchers import (  # noqa: E402
    stop_dsl_yaml_watcher as _stop_dsl_yaml_watcher,
)

__all__ = ("lifespan",)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения FastAPI.
    """
    from src.backend.dsl.commands.setup import register_action_handlers
    from src.backend.dsl.routes import register_dsl_routes
    from src.backend.plugins.composition.service_setup import register_all_services
    from src.backend.plugins.composition.setup_infra import ending, starting

    app_logger.info("Запуск приложения...")
    startup_completed = False

    # Sprint 1 V16 (R-V15-11): инициализация TaskRegistry singleton —
    # все asyncio.create_task в проекте проходят через него для
    # graceful shutdown и correlation_id propagation. Выносится ДО
    # try, чтобы finally-блок мог корректно вызвать shutdown_all даже
    # при падении в startup.
    task_registry = get_task_registry()
    app.state.task_registry = task_registry

    # Sprint 3 К2 W1: базовый OTel TracerProvider (W3C + B3 composite)
    # ставится сразу после TaskRegistry, чтобы любые последующие spans
    # (включая spans внутри register_all_services / Sentry init) шли в
    # корректный provider. По умолчанию выключено — управление через
    # env ``OTEL_ENABLED=true``.
    import os as _os

    if _os.environ.get("OTEL_ENABLED", "false").lower() == "true":
        try:
            from src.backend.infrastructure.observability.otel import configure_otel

            otel_exporter = _os.environ.get("OTEL_EXPORTER", "console")
            otel_endpoint = _os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None
            otel_service = _os.environ.get("OTEL_SERVICE_NAME", "gd_integration")
            otel_env = _os.environ.get("APP_ENVIRONMENT", "development")
            configure_otel(
                service_name=otel_service,
                exporter=otel_exporter,
                endpoint=otel_endpoint,
                environment=otel_env,
            )
        except Exception as otel_exc:
            app_logger.warning(
                "OTel baseline configure skipped: %s "
                "(приложение продолжит без базового TracerProvider)",
                otel_exc,
            )

    # Sprint 16 K2 W3 (L3-P0-1, 2026-05-20): OTel MeterProvider + OTLP
    # metrics exporter ставится отдельным блоком, чтобы lifespan мог
    # независимо включать traces и metrics. Default-OFF через ENV
    # ``OTLP_METRICS_ENABLED=true``. FastAPI/asyncpg/SQLAlchemy
    # auto-instrumentation подцепят глобальный MeterProvider после
    # set_meter_provider — workflow + business-event метрики
    # регистрируются базовыми meter-ами в _register_base_meters.
    if _os.environ.get("OTLP_METRICS_ENABLED", "false").lower() == "true":
        try:
            from src.backend.infrastructure.observability.otel import setup_otel_metrics

            metrics_endpoint = (
                _os.environ.get("OTLP_METRICS_ENDPOINT")
                or _os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
                or None
            )
            metrics_interval = int(
                _os.environ.get("OTLP_METRICS_EXPORT_INTERVAL_SECONDS", "60")
            )
            metrics_service = _os.environ.get("OTEL_SERVICE_NAME", "gd_integration")
            metrics_env = _os.environ.get("APP_ENVIRONMENT", "development")
            metrics_insecure = (
                _os.environ.get("OTLP_METRICS_INSECURE", "true").lower() == "true"
            )
            setup_otel_metrics(
                service_name=metrics_service,
                endpoint=metrics_endpoint,
                export_interval_seconds=metrics_interval,
                environment=metrics_env,
                insecure=metrics_insecure,
            )
        except Exception as metrics_exc:
            app_logger.warning(
                "OTel metrics configure skipped: %s "
                "(приложение продолжит без OTLP metrics-канала)",
                metrics_exc,
            )

    try:
        from src.backend.plugins.composition.di import register_app_state

        # Sprint 16 Wave 3 (CP-24, B-2, B-9): cross-settings ConfigValidator
        # как fail-fast startup gate. В production-окружении хотя бы одно
        # CRITICAL нарушение (например, WAF_STRICT=false) валит старт ДО
        # инициализации Sentry/Logging/DI — оператор обязан исправить
        # конфигурацию. В non-production нарушения логируются как WARNING
        # без блокировки.
        try:
            from src.backend.core.config.settings import settings as _cv_settings
            from src.backend.core.config.validator import (
                ConfigSeverity,
                ProductionConfigError,
                validate_startup_config,
            )
            from src.backend.core.config.waf import waf_settings as _cv_waf_settings

            _cv_violations = validate_startup_config(_cv_settings, _cv_waf_settings)
            for _cv_v in _cv_violations:
                _payload = (
                    "[%s] %s field=%s recommendation=%s context=%s",
                    _cv_v.code,
                    _cv_v.message,
                    _cv_v.field,
                    _cv_v.recommendation,
                    _cv_v.context,
                )
                if _cv_v.severity == ConfigSeverity.CRITICAL:
                    app_logger.critical(*_payload)
                elif _cv_v.severity == ConfigSeverity.WARNING:
                    app_logger.warning(*_payload)
                else:
                    app_logger.info(*_payload)
        except ProductionConfigError as cfg_exc:
            app_logger.critical(
                "Конфигурация production не прошла валидацию: %s", cfg_exc
            )
            raise
        except Exception as cfg_exc:
            app_logger.warning(
                "ConfigValidator skipped: %s "
                "(приложение продолжит без cross-settings проверки)",
                cfg_exc,
            )

        # Wave A: Sentry init выполняется в самом начале lifespan, чтобы
        # последующие падения регистрации сервисов попадали в error tracking.
        # Без SENTRY_DSN init возвращает False и не блокирует старт.
        try:
            from src.backend.infrastructure.observability.sentry_init import init_sentry

            init_sentry()
        except Exception as sentry_exc:
            app_logger.warning(
                "Sentry init skipped: %s (приложение продолжит без error tracking)",
                sentry_exc,
            )

        # Wave 2.5: инициализация LogSink-стека (router + sinks по профилю)
        # должна произойти ДО регистрации сервисов, чтобы их startup-логи
        # уже доезжали до sink-ов (Console JSON / Disk Rotating / Graylog).
        # Падение инициализации не должно блокировать старт — приложение
        # продолжит работать с legacy stdlib-логированием.
        try:
            from src.backend.infrastructure.logging import init_log_sinks

            init_log_sinks()
        except Exception as log_exc:
            app_logger.warning(
                "LogSink router init skipped: %s (приложение продолжит на stdlib-логах)",
                log_exc,
            )

        register_app_state(app)
        _register_storage_singletons(app)

        # Sprint 3 К2 W1: подключение Redis cluster adapter под env-flag
        # ``REDIS_CLUSTER_ENABLED=true``. По умолчанию выключено — single-
        # node Redis из infrastructure/clients/storage/redis.py продолжает
        # работать как раньше. Узлы конфигурируются через
        # ``REDIS_CLUSTER_NODES="host1:6379,host2:6379,host3:6379"``.
        if _os.environ.get("REDIS_CLUSTER_ENABLED", "false").lower() == "true":
            try:
                nodes_env = _os.environ.get("REDIS_CLUSTER_NODES", "").strip()
                if not nodes_env:
                    app_logger.warning(
                        "REDIS_CLUSTER_ENABLED=true, но REDIS_CLUSTER_NODES пуст — пропуск"
                    )
                else:
                    from redis.asyncio.cluster import ClusterNode

                    from src.backend.infrastructure.cache.redis_cluster import (
                        RedisClusterAdapter,
                    )

                    parsed_nodes: list[ClusterNode] = []
                    for node_entry in nodes_env.split(","):
                        host, _, port = node_entry.strip().partition(":")
                        if not host:
                            continue
                        parsed_nodes.append(
                            ClusterNode(host=host, port=int(port or 6379))
                        )

                    cluster_password = _os.environ.get("REDIS_CLUSTER_PASSWORD") or None
                    adapter = RedisClusterAdapter(
                        startup_nodes=parsed_nodes,
                        max_connections=int(
                            _os.environ.get("REDIS_CLUSTER_MAX_CONNECTIONS", "50")
                        ),
                        socket_keepalive=True,
                        health_check_interval=int(
                            _os.environ.get("REDIS_CLUSTER_HEALTH_CHECK_INTERVAL", "30")
                        ),
                        password=cluster_password,
                    )
                    app.state.redis_cluster_adapter = adapter
                    app_logger.info(
                        "RedisClusterAdapter зарегистрирован: nodes=%d",
                        len(parsed_nodes),
                    )
            except Exception as rc_exc:
                app_logger.warning(
                    "RedisClusterAdapter bootstrap skipped: %s "
                    "(приложение продолжит без cluster-режима)",
                    rc_exc,
                )

        register_all_services()

        # Wave 1.6 (S1): AI Safety cleanup-loop запускается через
        # TaskRegistry, чтобы корректно отмениться на shutdown
        # (R-V15-11 leak prevention).
        try:
            from src.backend.plugins.composition.ai_safety_setup import start_ai_safety

            await start_ai_safety(app)
        except Exception as ai_safety_exc:
            app_logger.warning(
                "AI safety bootstrap skipped: %s "
                "(приложение продолжит без AI workspace cleanup-loop)",
                ai_safety_exc,
            )

        register_action_handlers()
        register_dsl_routes()
        _bootstrap_resilience_coordinator(app)
        _bootstrap_snapshot_job(app)
        await _start_dsl_yaml_watcher(app)
        await starting()
        await _register_protocol_providers()
        _validate_cache_layers()

        # Wave 4-tail: PluginLoader bootstrap (in-tree + entry_points).
        # in-tree плагины из plugins/<dir>/plugin.yaml загружаются явно;
        # entry_points плагины — через importlib.metadata.entry_points.
        # Падения отдельных плагинов не блокируют startup.
        try:
            from pathlib import Path

            from src.backend.services.plugins import get_plugin_loader

            loader = get_plugin_loader()
            plugins_dir = Path("plugins")
            if plugins_dir.is_dir():
                for entry_raw in plugins_dir.iterdir():
                    if not entry_raw.is_dir():
                        continue
                    entry = (
                        entry_raw  # Path.iterdir() returns Path objects in Python 3.14
                    )
                    if (entry / "plugin.yaml").is_file():
                        try:
                            await loader.load_from_path(entry)
                        except Exception as plugin_exc:
                            app_logger.warning(
                                "In-tree plugin %s skipped: %s", entry.name, plugin_exc
                            )
            try:
                await loader.discover_and_load()
            except Exception as ep_exc:
                app_logger.warning("entry_points plugin discovery skipped: %s", ep_exc)
            app.state.plugin_loader = loader
        except Exception as exc:
            app_logger.warning("Plugin loader bootstrap skipped: %s", exc)

        # R1.fin (V11): bootstrap PluginLoaderV11 + RouteLoader под feature-flag.
        # Default OFF — wave 4.4 PluginLoader продолжает работать как раньше.
        await _bootstrap_v11_plugin_loader(app)
        await _bootstrap_v11_route_loader(app)
        await _start_v11_hot_reload(app)

        try:
            from src.backend.workflows.outbox_worker import start_outbox_worker

            start_outbox_worker(interval_seconds=5, batch_size=100)
        except Exception as exc:
            # Outbox-worker не критичен для базовой работоспособности
            # (например, dev_light без RabbitMQ) — startup продолжается.
            app_logger.warning("Outbox worker registration skipped: %s", exc)

        # S72 W2 / S74 W1: outbox stuck-monitor — periodic Prometheus
        # gauge update (60s sample, 300s threshold). Default-OFF через
        # feature flag stuck_monitor_enabled.
        try:
            from src.backend.core.config.features import feature_flags
            from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
                start_outbox_stuck_monitor,
            )

            if getattr(feature_flags, "stuck_monitor_enabled", False):
                threshold = int(
                    getattr(feature_flags, "stuck_monitor_threshold_seconds", 300)
                )
                sample_interval = int(
                    getattr(feature_flags, "stuck_monitor_sample_interval_seconds", 60)
                )
                await start_outbox_stuck_monitor(
                    threshold_seconds=threshold, sample_interval_seconds=sample_interval
                )
                app_logger.info(
                    "OutboxStuckMonitor started (threshold=%ds, sample=%ds)",
                    threshold,
                    sample_interval,
                )
        except Exception as exc:
            app_logger.warning("OutboxStuckMonitor registration skipped: %s", exc)

        # К3 (Sprint 4 V16.1): bootstrap workflow runtime — LiteTemporal
        # для dev_light, реальный Temporal для staging/prod. Не блокирует
        # startup при отсутствии SDK или ошибке backend'а.
        try:
            from src.backend.plugins.composition.workflow_setup import (
                start_workflow_runtime,
            )

            await start_workflow_runtime(app)
        except Exception as wf_exc:
            app_logger.warning("Workflow runtime startup skipped: %s", wf_exc)

        # Wave S1/DSL Foundation (Step 6): заполняем ServiceSchemaRegistry
        # после загрузки плагинов и маршрутов. Singleton доступен через
        # GET /api/v1/admin/schemas (admin_schemas router).
        try:
            from src.backend.services.schema_registry import (
                get_schema_registry,
                populate_from_actions,
                populate_from_manifests,
                populate_from_processor_registry,
                populate_from_routes,
            )

            schema_registry = get_schema_registry()
            populate_from_processor_registry(schema_registry)
            populate_from_routes(registry=schema_registry)
            populate_from_actions(schema_registry)
            populate_from_manifests(schema_registry)
            app.state.schema_registry = schema_registry
            app_logger.info(
                "ServiceSchemaRegistry заполнен: %s", schema_registry.summary()
            )
        except Exception as sr_exc:
            app_logger.warning("ServiceSchemaRegistry bootstrap skipped: %s", sr_exc)

        # Sprint 17 K5 W1 (D9): запуск Redis pub/sub broadcaster для
        # multi-replica propagation feature-flag overrides. Default-OFF
        # через ``tenant_feature_flag_ui`` (backbone S17). Никогда не
        # валит startup — graceful no-op при недоступности Redis.
        try:
            from src.backend.core.feature_flags.redis_broadcaster import (
                maybe_start_broadcaster,
            )
            from src.backend.core.feature_flags.runtime_overrides import (
                get_runtime_overrides,
            )
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client,
            )

            redis_kv = getattr(get_redis_client(), "client", None)
            broadcaster = await maybe_start_broadcaster(
                redis_client=redis_kv, overrides=get_runtime_overrides()
            )
            if broadcaster is not None:
                app.state.feature_flag_broadcaster = broadcaster
                app_logger.info(
                    "FeatureFlagBroadcaster registered: replica_id=%s",
                    broadcaster.replica_id,
                )
        except Exception as bcast_exc:
            app_logger.warning(
                "FeatureFlagBroadcaster bootstrap skipped: %s "
                "(приложение продолжит без multi-replica propagation)",
                bcast_exc,
            )

        startup_completed = True
        app.state.infrastructure_ready = True

        from src.backend.dsl.commands.registry import action_handler_registry
        from src.backend.dsl.registry import route_registry

        app_logger.info(
            "Приложение успешно запущено: %d actions, %d DSL-маршрутов",
            len(action_handler_registry.list_actions()),
            len(route_registry.list_routes()),
        )
        yield

    except Exception as exc:
        if not startup_completed:
            app_logger.critical(
                "Критическая ошибка при запуске приложения: %s", str(exc), exc_info=True
            )
            raise RuntimeError(
                "Остановка приложения из-за ошибки инициализации"
            ) from exc

        app_logger.critical(
            "Критическая ошибка во время работы приложения: %s", str(exc), exc_info=True
        )
        raise

    finally:
        app_logger.info("Завершение работы приложения...")
        app.state.infrastructure_ready = False

        # К3: shutdown workflow runtime до stop_dsl_yaml_watcher,
        # чтобы worker'ы успели завершить свои workflow до закрытия DSL.
        try:
            from src.backend.plugins.composition.workflow_setup import (
                start_workflow_runtime,
            )
            from src.backend.workflows.outbox_worker import stop_outbox_worker

            await stop_outbox_worker()
        except Exception as wf_stop_exc:
            app_logger.warning("Workflow runtime shutdown error: %s", wf_stop_exc)

        # S74 W1: stop outbox stuck-monitor (graceful drain).
        try:
            from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
                stop_outbox_stuck_monitor,
            )

            await stop_outbox_stuck_monitor()
        except Exception as exc:
            app_logger.debug("OutboxStuckMonitor stop skipped: %s", exc)

        await _stop_dsl_yaml_watcher(app)

        # Wave 1.6 (S1): остановка AI Safety cleanup-loop ДО V11-loaders
        # (плагины могут писать в workspace через AIFsFacade на shutdown).
        try:
            from src.backend.plugins.composition.ai_safety_setup import stop_ai_safety

            await stop_ai_safety(app)
        except Exception as ai_safety_stop_exc:
            app_logger.warning("AI safety shutdown error: %s", ai_safety_stop_exc)

        # R1.fin (V11): shutdown V11-loader'ов в обратном порядке
        # (route → plugin) ДО Wave 4 PluginLoader, чтобы их on_shutdown
        # успел отработать до закрытия общих ресурсов.
        await _shutdown_v11_loaders(app)

        # Wave 4-tail: graceful plugin shutdown — каждому плагину
        # даётся on_shutdown() до общего ending().
        plugin_loader = getattr(app.state, "plugin_loader", None)
        if plugin_loader is not None:
            try:
                await plugin_loader.shutdown_all()
            except Exception as plugin_exc:
                app_logger.warning("Plugin shutdown error: %s", plugin_exc)

        try:
            await ending()
        except Exception as shutdown_exc:
            app_logger.error(
                "Ошибка при завершении работы приложения: %s",
                str(shutdown_exc),
                exc_info=True,
            )

        app_logger.info("Приложение остановлено")

        # Wave 2.5: финальный flush + close всех LogSink-ов. Делается
        # после ``ending()`` и финального лога, чтобы зафиксировать в
        # sink-ах все события штатной остановки.
        try:
            from src.backend.infrastructure.logging import shutdown_log_sinks

            await shutdown_log_sinks()
        except Exception as sink_exc:
            app_logger.warning("LogSink shutdown error: %s", sink_exc)

        # Sprint 1 V16 Step 3.4: pyrate_limiter Leaker shutdown-hook.
        # Singleton Limiter из get_default_limiter() запускает фоновую
        # `_leaker.aio_leak_task`, которая течёт без явной остановки.
        # Canonical helper — core/resilience/_pyrate_compat.py.
        try:
            from src.backend.core.resilience._pyrate_compat import (
                shutdown_pyrate_leaker,
            )
            from src.backend.entrypoints.dependencies.rate_limit import (
                get_default_limiter,
            )

            await shutdown_pyrate_leaker(get_default_limiter())
        except Exception as leaker_exc:
            app_logger.warning("pyrate Leaker shutdown skipped: %s", leaker_exc)

        # Sprint 16 K2 W3 (L3-P0-1): graceful shutdown OTel MeterProvider.
        # PeriodicExportingMetricReader должен успеть отправить накопленные
        # метрики в OTLP-коллектор перед остановкой приложения.
        # No-op, если setup_otel_metrics не вызывался.
        try:
            from src.backend.infrastructure.observability.otel import (
                shutdown_otel_metrics,
            )

            shutdown_otel_metrics()
        except Exception as metrics_stop_exc:
            app_logger.warning("OTel metrics shutdown skipped: %s", metrics_stop_exc)

        # Sprint 3 К2 W1: graceful close RedisClusterAdapter если регистрировался.
        cluster_adapter = getattr(app.state, "redis_cluster_adapter", None)
        if cluster_adapter is not None:
            try:
                await cluster_adapter.close()
            except Exception as rc_close_exc:
                app_logger.warning("RedisClusterAdapter close error: %s", rc_close_exc)

        # Sprint 17 K5 W1 (D9): graceful stop FeatureFlagBroadcaster
        # ДО task_registry.shutdown_all, чтобы subscriber-task успел
        # отписаться от Redis pub/sub корректно (а не быть отменённым).
        bcast = getattr(app.state, "feature_flag_broadcaster", None)
        if bcast is not None:
            try:
                await bcast.stop()
            except Exception as bcast_stop_exc:
                app_logger.warning(
                    "FeatureFlagBroadcaster shutdown error: %s", bcast_stop_exc
                )

        # Sprint 1 V16 (R-V15-11): graceful cancel всех зарегистрированных
        # фоновых задач. Делается ПОСЛЕ ending()/log shutdown, чтобы тех
        # задачи, которые ещё могли логировать остановку, успели завершиться.
        try:
            await task_registry.shutdown_all(timeout=10)
        except Exception as tr_exc:
            app_logger.warning("TaskRegistry shutdown error: %s", tr_exc)
