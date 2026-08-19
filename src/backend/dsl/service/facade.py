from functools import lru_cache
from typing import Any

from src.backend.core.errors import RoutePermissionDeniedError
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.registry import route_registry

__all__ = ("DslService", "get_dsl_service")


class DslService:
    """Facade над RouteRegistry + ExecutionEngine.

    Нужен для entrypoints, чтобы они не работали
    напрямую с low-level объектами DSL.
    """

    def __init__(self, engine: ExecutionEngine | None = None) -> None:
        self._engine = engine or ExecutionEngine()

    async def dispatch(
        self,
        route_id: str,
        *,
        body: Any = None,
        headers: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
    ) -> Exchange[Any]:
        """Выполняет зарегистрированный DSL-маршрут.

        Args:
            route_id: Идентификатор маршрута.
            body: Тело входного сообщения.
            headers: Заголовки входного сообщения.
            context: Runtime context (если ``None`` — создаётся пустой).

        Returns:
            Exchange[Any]: Итоговый Exchange.

        Raises:
            RouteDisabledError: Маршрут заблокирован feature-флагом.
            RoutePermissionDeniedError: K3 S19 W3 — маршрут декларирует
                ``requires_permission`` в ``route.toml [security]``, но
                principal не прошёл :func:`check_route_permission`.
            KeyError: Маршрут не зарегистрирован.
            RoutePermissionDeniedError: principal не имеет требуемой
                permission (V22 R-V15-1 / Sprint 1).

        """
        if context is None:
            context = ExecutionContext()
        pipeline = route_registry.get(route_id)
        # K3 S19 W3: route-level authorization enforcement.
        # Pipeline.security заполняется RouteLoader'ом из
        # ``manifest.security.requires_permission``. Непустой кортеж —
        # сигнал для вызова AuthorizationGateway через check_route_permission.
        # Если security=None/empty — поведение backward-compat (no check).
        if pipeline.security:
            await self._enforce_route_permission(
                pipeline.route_id, pipeline.security, context
            )
        return await self._engine.execute(
            pipeline, body=body, headers=headers, context=context
        )

    @staticmethod
    async def _enforce_route_permission(
        route_id: str,
        required_permissions: tuple[str, ...],
        context: ExecutionContext | None,
    ) -> None:
        """K3 S19 W3: вызывает ``check_route_permission`` и валит на deny.

        Principal и фактические permissions берутся из
        :class:`ExecutionContext`; пустые значения трактуются как
        ``"anonymous"`` / ``()`` — это fail-closed при включённом
        feature-flag.
        Импорт локальный, чтобы не создавать циклическую зависимость
        ``services.routes.route_authz`` → ``dsl`` (см. ADR-043 layering).
        """
        from src.backend.services.routes.route_authz import check_route_permission

        ctx_dict: dict[str, Any] = {"route_id": route_id}
        principal = "anonymous"
        actual_permissions: tuple[str, ...] = ()
        if context is not None:
            principal = context.principal or "anonymous"
            actual_permissions = context.permissions or ()
            ctx_dict["correlation_id"] = context.route_id or ""
        # Фактические permissions-principal'а передаём в ctx — permission_step
        # читает ``ctx["permissions"]`` (см. permission_mixin.permission_step).
        ctx_dict["permissions"] = actual_permissions
        allowed, reason = await check_route_permission(
            route_id=route_id,
            principal=principal,
            permissions=required_permissions,
            context=ctx_dict,
        )
        if not allowed:
            raise RoutePermissionDeniedError(route_id=route_id, reason=reason)

    @staticmethod
    def list_routes() -> tuple[str, ...]:
        """Список всех зарегистрированных маршрутов."""
        return route_registry.list_routes()

    @staticmethod
    def list_enabled_routes() -> tuple[str, ...]:
        """Список маршрутов, доступных для выполнения."""
        return route_registry.list_enabled_routes()

    @staticmethod
    def list_disabled_routes() -> tuple[str, ...]:
        """Список маршрутов, заблокированных feature-флагом."""
        return route_registry.list_disabled_routes()

    @staticmethod
    def get_feature_flags() -> dict[str, str]:
        """Маппинг route_id → feature_flag."""
        return route_registry.get_route_feature_flags()

    @staticmethod
    def get_route_overrides(route_id: str) -> dict[str, Any]:
        """S163 W15: возвращает route_overrides из Pipeline (или {}).

        Используется handlers (ws_handler, grpc_server, graphql) для
        per-action override стандартных settings (timeout/pool/msg_size).

        Args:
            route_id: Идентификатор маршрута.

        Returns:
            Dict с override values (e.g. ``{"pool_size": 50, "message_timeout_s": 5.0}``).

        """
        return route_registry.get_route_overrides(route_id)

    @staticmethod
    def toggle_feature_flag(flag_name: str, *, enable: bool) -> None:
        """Включает/отключает feature-флаг.

        Args:
            flag_name: Имя feature-флага.
            enable: ``True`` — маршруты доступны,
                ``False`` — заблокированы.

        """
        route_registry.toggle_feature_flag(flag_name, enable=enable)


@lru_cache(maxsize=1)
def get_dsl_service() -> DslService:
    """Возвращает facade DSL.

    Singleton на процесс (R1.4): `ExecutionEngine` создаётся один раз,
    устраняя linear scan `_find_timeout_middleware` при каждом вызове.
    """
    return DslService()
