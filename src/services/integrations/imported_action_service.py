"""W24/pre-W26 — :class:`ImportedActionService`: каталог + dispatch импортированных endpoint'ов.

Назначение
==========
``ImportService._register_actions`` теперь регистрирует **один сервис** в
:class:`ActionHandlerRegistry` через kw-only API и сохраняет endpoint-метаданные
в :class:`ImportedActionService` (singleton). Dispatch выполняется через
``service_method="dispatch_endpoint"`` — единый вход для всех импортированных
действий.

Stub-семантика сохранена: ``dispatch_endpoint`` возвращает метаданные endpoint'а
и payload (round-trip smoke-тест W24). Реальный invocation через ``Invoker``
(W22) подключается отдельно.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.di import app_state_singleton
from src.core.models.connector_spec import EndpointSpec

__all__ = (
    "EndpointMeta",
    "ImportedActionService",
    "get_imported_action_service",
)


@dataclass(slots=True, frozen=True)
class EndpointMeta:
    """Лёгкий снимок ``EndpointSpec`` для диспатча.

    Attrs:
        operation_id: Уникальный id операции из исходного spec'а.
        method: HTTP-метод (``GET``/``POST``/...) или SOAP-action.
        path: Путь endpoint'а или SOAP-operation-name.
    """

    operation_id: str
    method: str
    path: str

    @classmethod
    def from_spec(cls, spec: EndpointSpec) -> "EndpointMeta":
        """Сжать ``EndpointSpec`` до минимального dispatch-снимка."""
        return cls(operation_id=spec.operation_id, method=spec.method, path=spec.path)


class ImportedActionService:
    """Каталог импортированных endpoint'ов + единая точка диспатча.

    Один экземпляр (singleton через app.state) обслуживает все action'ы
    вида ``connector.{name}.{operation_id}``. Каждый ``register_endpoint``
    добавляет запись в каталог; ``dispatch_endpoint`` возвращает stub
    с метаданными (полноценный invocation подключается через Invoker
    отдельно).
    """

    def __init__(self) -> None:
        self._endpoints: dict[str, EndpointMeta] = {}

    def register_endpoint(self, action: str, endpoint: EndpointSpec) -> None:
        """Сохраняет endpoint-метаданные под action-именем.

        Args:
            action: Action-name (``connector.{spec_name}.{operation_id_short}``).
            endpoint: Исходный :class:`EndpointSpec` из ``ConnectorSpec``.
        """
        self._endpoints[action] = EndpointMeta.from_spec(endpoint)

    def is_registered(self, action: str) -> bool:
        """Возвращает ``True`` если action присутствует в каталоге."""
        return action in self._endpoints

    def list_actions(self) -> tuple[str, ...]:
        """Сортированный список зарегистрированных action-имён."""
        return tuple(sorted(self._endpoints))

    def clear(self) -> None:
        """Очищает каталог (используется в тестах между сценариями)."""
        self._endpoints.clear()

    async def dispatch_endpoint(
        self, *, action: str, **payload: Any
    ) -> dict[str, Any]:
        """Stub-диспатч импортированного endpoint'а.

        Args:
            action: Action-name, по которому ищется endpoint в каталоге.
            **payload: Произвольный payload (передаётся в результат как есть).

        Returns:
            ``{status: "stub", operation_id, method, path, payload}``.

        Raises:
            KeyError: Если action не зарегистрирован.
        """
        meta = self._endpoints[action]
        return {
            "status": "stub",
            "operation_id": meta.operation_id,
            "method": meta.method,
            "path": meta.path,
            "payload": payload,
        }


@app_state_singleton(
    "imported_action_service", factory=lambda: ImportedActionService()
)
def get_imported_action_service() -> ImportedActionService:
    """Singleton-аксессор :class:`ImportedActionService`."""
    raise RuntimeError("unreachable — фабрика создаёт ImportedActionService()")
