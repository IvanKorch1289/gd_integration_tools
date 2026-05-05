"""W24 — :class:`ImportService` orchestration над ImportGateway.

Шаги import_and_register:

1. Вычисление SHA256 hash → проверка через ``ConnectorConfigStore.get``;
   если hash совпадает с предыдущим импортом и ``force=False`` —
   возвращаем idempotent-skip.
2. Выбор backend через ``build_import_gateway(kind)``.
3. Парсинг content → ``ConnectorSpec``.
4. Persist в Mongo (коллекция ``connector_configs``) — упаковываем
   ``ConnectorSpec`` в dict через ``asdict``.
5. (Опц.) регистрация actions в ``ActionHandlerRegistry`` через
   ``connector.{name}.{operation_id}`` — best-effort, при отсутствии
   action_handler_registry в DI просто логируется.
6. Orphan-cleanup: удаление route-id, которые больше не присутствуют в
   обновлённом spec'е.

Контракт минимальный: на вход — :class:`ImportSource`, на выход — dict с
сводкой (``status``, ``connector``, ``endpoints``, ``secret_refs_required``).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.import_gateway import ImportSource
from src.backend.core.models.connector_spec import ConnectorSpec

__all__ = ("ImportService", "get_import_service")

logger = logging.getLogger("services.integrations.import_service")


class ImportService:
    """Orchestration: ImportGateway → idempotency → persist → register."""

    def __init__(
        self, connector_store: Any | None = None, action_registry: Any | None = None
    ) -> None:
        """Args:
        connector_store: ``ConnectorConfigStore`` (из DI). Если ``None`` —
            берётся через :func:`get_connector_config_store` lazy.
        action_registry: ``ActionHandlerRegistry`` (опционально). Если
            ``None`` — регистрация actions пропускается (тесты, dev_light).
        """
        self._connector_store = connector_store
        self._action_registry = action_registry

    async def import_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Action-обёртка над :meth:`import_and_register` для DSL.

        Args:
            payload: ``{kind, content, prefix?, source_url?, force?, dry_run?}``.

        Returns:
            Результат ``import_and_register``.

        Raises:
            ValueError: Невалидный payload.
        """
        from src.backend.core.interfaces.import_gateway import ImportSourceKind

        try:
            kind = ImportSourceKind(payload["kind"])
            content = payload["content"]
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"import_action: payload требует 'kind' и 'content': {exc}"
            ) from exc
        source = ImportSource(
            kind=kind,
            content=content,
            prefix=payload.get("prefix", "ext"),
            source_url=payload.get("source_url"),
        )
        return await self.import_and_register(
            source,
            force=bool(payload.get("force", False)),
            register_actions=not bool(payload.get("dry_run", False)),
        )

    async def list_imported(self) -> dict[str, Any]:
        """Возвращает список ранее импортированных коннекторов из Mongo."""
        store = self._resolve_store()
        if store is None:
            return {"connectors": [], "store_available": False}
        try:
            entries = await store.list_all()
        except Exception as exc:
            logger.warning("ImportService.list_imported: %s", exc)
            return {"connectors": [], "store_available": False, "error": str(exc)}
        return {
            "connectors": [
                {
                    "name": e.name,
                    "version": e.version,
                    "source_kind": (e.config or {}).get("source_kind"),
                    "endpoints": len((e.config or {}).get("endpoints", [])),
                    "updated_at": e.updated_at.isoformat() if e.updated_at else None,
                }
                for e in entries
            ],
            "store_available": True,
        }

    async def import_and_register(
        self,
        source: ImportSource,
        *,
        force: bool = False,
        register_actions: bool = True,
    ) -> dict[str, Any]:
        """Полный цикл импорта.

        Args:
            source: Описание импортируемой спецификации.
            force: Если ``True`` — игнорировать idempotency-check и
                перезаписать spec даже при совпадающем hash.
            register_actions: Если ``True`` — регистрировать actions в
                ActionHandlerRegistry (best-effort).

        Returns:
            dict со статусом:
            ``{status, connector, version, endpoints, secret_refs_required, removed_orphans}``.
        """
        from src.backend.core.di.providers import get_import_gateway_factory_provider

        gateway = get_import_gateway_factory_provider()(source.kind)
        spec = await gateway.import_spec(source)

        store = self._resolve_store()
        previous = await self._safe_get(store, spec.name) if store else None
        previous_hash = (previous.config or {}).get("source_hash") if previous else None

        if previous_hash == spec.source_hash and not force:
            logger.info(
                "ImportService: idempotent skip для %s (hash совпадает)", spec.name
            )
            return {
                "status": "skipped",
                "reason": "spec_hash_unchanged",
                "connector": spec.name,
                "version": previous.version if previous else 0,
                "endpoints": len(spec.endpoints),
                "secret_refs_required": self._secret_refs_summary(spec),
                "removed_orphans": [],
            }

        config_dict = asdict(spec)

        saved = None
        if store is not None:
            try:
                saved = await store.save(
                    spec.name, config_dict, enabled=True, user=None
                )
            except Exception as exc:
                logger.warning(
                    "ImportService: persist в connector_configs failed (%s); spec parsed но не сохранён",
                    exc,
                )

        registered_actions: list[str] = []
        if register_actions and self._action_registry is not None:
            registered_actions = self._register_actions(spec)

        removed_orphans = self._compute_removed_endpoints(previous, spec)

        return {
            "status": "imported" if not previous else "updated",
            "connector": spec.name,
            "version": saved.version if saved else 1,
            "endpoints": len(spec.endpoints),
            "registered_actions": registered_actions,
            "secret_refs_required": self._secret_refs_summary(spec),
            "removed_orphans": removed_orphans,
        }

    @staticmethod
    async def _safe_get(store: Any, name: str) -> Any | None:
        """Безопасный .get(): при ошибке инфры возвращает None."""
        try:
            return await store.get(name)
        except Exception as exc:
            logger.warning(
                "ImportService: connector_config_store.get(%s) failed: %s — продолжаем без previous",
                name,
                exc,
            )
            return None

    def _resolve_store(self) -> Any | None:
        if self._connector_store is not None:
            return self._connector_store
        try:
            from src.backend.core.di.providers import (
                get_connector_config_store_provider,
            )

            return get_connector_config_store_provider()
        except Exception as exc:
            logger.warning(
                "ImportService: connector_config_store недоступен (%s), импорт без persist",
                exc,
            )
            return None

    @staticmethod
    def _secret_refs_summary(spec: ConnectorSpec) -> list[dict[str, str]]:
        """Список SecretRef-ов, которые нужно загрузить в SecretsBackend."""
        if spec.auth is None:
            return []
        return [
            {"key": k, "ref": ref.ref, "hint": ref.hint}
            for k, ref in spec.auth.secret_refs.items()
        ]

    @staticmethod
    def _compute_removed_endpoints(
        previous: Any | None, current: ConnectorSpec
    ) -> list[str]:
        """Возвращает operation_id, которые были раньше, но исчезли в новом spec."""
        if previous is None:
            return []
        prev_config = previous.config or {}
        prev_endpoints = prev_config.get("endpoints", []) or []
        prev_ids = {
            ep.get("operation_id") for ep in prev_endpoints if ep.get("operation_id")
        }
        current_ids = {ep.operation_id for ep in current.endpoints}
        return sorted(prev_ids - current_ids)

    def _register_actions(self, spec: ConnectorSpec) -> list[str]:
        """Best-effort регистрация actions в ActionHandlerRegistry (kw-only API).

        Каждый endpoint регистрируется в singleton'е :class:`ImportedActionService`
        и в реестре указывается ``service_method="dispatch_endpoint"`` —
        фактический dispatch выполняется через единую точку входа.

        Action-name = ``connector.{spec.name}.{operation_id_short}``.
        """
        registered: list[str] = []
        registry = self._action_registry
        if registry is None or not hasattr(registry, "register"):
            return registered

        from src.backend.services.integrations.imported_action_service import (
            get_imported_action_service,
        )

        catalog = get_imported_action_service()
        for ep in spec.endpoints:
            short = ep.operation_id.rsplit(".", 1)[-1]
            action_name = f"connector.{spec.name}.{short}"
            try:
                catalog.register_endpoint(action_name, ep)
                registry.register(
                    action=action_name,
                    service_getter=get_imported_action_service,
                    service_method="dispatch_endpoint",
                )
                registered.append(action_name)
            except Exception as exc:
                logger.warning(
                    "ImportService: failed to register action %s: %s", action_name, exc
                )
        return registered


@app_state_singleton("import_service", factory=ImportService)
def get_import_service() -> ImportService:
    """Singleton-аксессор :class:`ImportService`."""
    raise RuntimeError("unreachable — фабрика создаёт ImportService()")
