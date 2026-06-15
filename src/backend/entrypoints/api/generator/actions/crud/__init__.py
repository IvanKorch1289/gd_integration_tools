"""CrudMixin package (S58 W1 decomp from crud.py 669 LOC).

14 methods decomposed в 4 mixin files:
- ``read_mixin.py`` (4): _register_route, _register_get_all, _register_get_by_id, _register_get_first_or_last
- ``write_mixin.py`` (5): _register_create, _register_create_many, _register_update, _register_delete, _register_all_versions
- ``versioning_mixin.py`` (3): _register_latest_version, _register_restore, _register_changes
- ``query_mixin.py`` (1): _register_filter

Core (1) остается в __init__.py: _register_crud_action_metadata.

Backward-compat: ``from src.backend.entrypoints.api.generator.actions.crud import CrudMixin`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
from pydantic import BaseModel
from src.backend.core.interfaces.action_dispatcher import ActionMetadata
from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.entrypoints.api.generator.actions.crud.query_mixin import (
    QueryMixin,  # S58 W1: MRO
)
from src.backend.entrypoints.api.generator.actions.crud.read_mixin import (
    ReadMixin,  # S58 W1: MRO
)
from src.backend.entrypoints.api.generator.actions.crud.versioning_mixin import (
    VersioningMixin,  # S58 W1: MRO
)
from src.backend.entrypoints.api.generator.actions.crud.write_mixin import (
    WriteMixin,  # S58 W1: MRO
)
from src.backend.entrypoints.api.generator.specs import (
    CrudSpec,
    HttpMethod,
    )

__all__ = ("CrudMixin",)


class CrudMixin(ReadMixin, WriteMixin, VersioningMixin, QueryMixin):
    """CRUD action mixin (4 mixins = 13 methods + 1 core)."""

    __slots__ = ()

    # Маппинг CRUD-глагол → имя метода на сервисе.
    # Используется в ``_register_crud_action_metadata`` для регистрации
    # handler в ``action_handler_registry``. S124 W2: восстановлено
    # (потеряно при S65 decomp).
    _CRUD_VERB_TO_SERVICE_METHOD: dict[str, str] = {
        "list": "list",
        "get": "get",
        "create": "create",
        "create_many": "bulk_create",
        "update": "update",
        "delete": "delete",
    }

    @classmethod
    def _register_crud_action_metadata(
        cls,
        *,
        spec: CrudSpec,
        verb: str,
        method: HttpMethod,
        path: str,
        description: str,
        input_model: type[BaseModel] | None,
        output_model: type[BaseModel] | None,
    ) -> str:
        """Регистрирует Tier 1 action для CRUD-роута: handler + metadata.

        Wave 1.1 (Roadmap V10): каждый CRUD-роут, создаваемый
        :class:`ActionRouterBuilder`, дополнительно регистрирует
        соответствующий action в ``action_handler_registry`` с
        ``tier=1``-семантикой. Идентификатор формируется по конвенции
        F.8 ``"<resource>.<verb>"``.

        Регистрация:

        * ``register_with_metadata`` сохраняет :class:`ActionMetadata`
          (transports/side_effect/idempotent/tags) для Gateway/Developer
          portal;
        * ``register`` привязывает handler через ``service_getter`` +
          метод BaseService по конвенции (см.
          :attr:`_CRUD_VERB_TO_SERVICE_METHOD`). Если action с тем же
          именем уже зарегистрирован (например, ``orders.get`` из
          ``setup.register_action_handlers``) — повторная регистрация
          перезаписывает handler идентичной семантикой (idempotent).

        Args:
            spec: CRUD-описание ресурса.
            verb: Глагол action ("list", "get", "create", "create_many",
                "update", "delete").
            method: HTTP-метод роута для вывода ``side_effect``/
                ``idempotent`` через REST-конвенцию.
            path: Полный path роута (для трассировки/документации).
            description: Описание для OpenAPI и developer portal.
            input_model: Pydantic-модель payload (тело или путь).
            output_model: Pydantic-модель ответа.

        Returns:
            Сформированный ``action_id``.
        """
        action_id = f"{spec.name}.{verb}"
        side_effect = "read" if method.upper() == "GET" else "write"
        idempotent = method.upper() in {"GET", "PUT", "DELETE", "HEAD", "OPTIONS"}
        metadata = ActionMetadata(
            action=action_id,
            description=description,
            input_model=input_model,
            output_model=output_model,
            transports=("http", "grpc", "graphql"),
            side_effect=side_effect,
            idempotent=idempotent,
            tags=tuple(spec.tags),
        )
        action_handler_registry.register_with_metadata(
            action=action_id, handler=None, metadata=metadata
        )
        service_method = cls._CRUD_VERB_TO_SERVICE_METHOD.get(verb)
        if service_method is not None:
            action_handler_registry.register(
                action=action_id,
                service_getter=spec.service_getter,
                service_method=service_method,
                payload_model=input_model,
            )
        return action_id
