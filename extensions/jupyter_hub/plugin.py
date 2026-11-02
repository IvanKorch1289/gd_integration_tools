"""Capability-провайдер Jupyter Hub (ADR-0415).

Зачем этот плагин
-----------------
Capability ``jupyter.hub`` (scope ``run``) объявлена в vocabulary
(:mod:`core.security.capabilities.vocabulary.defaults.base`), но **владельца**
capability в проекте не было: ни один плагин не объявлял
``[[capabilities]] name = "jupyter.hub"``. Из-за этого subset-инвариант
ADR-044 (``route.capabilities ⊆ union(requires_plugins) ∪ public``) отклонял
``routes/jupyter_hub_run`` с ``capability_superset`` — роут оставался
единственным неработающим из семи.

Этот плагин — **владелец** capability: он объявляет её в своём
``plugin.toml`` (ADR-0078) и тем самым разрешает роуту её запросить
(``[route.requires_plugins] jupyter_hub = ">=0.1,<1.0"``).

Least privilege
---------------
Capability намеренно **не публичная**: запуск ноутбука на удалённом
Jupyter Hub = выполнение произвольного пользовательского кода с сервисной
учёткой. Публичность отдала бы эту операцию любому роуту без провайдера
(ADR-0405 §Альтернативы, вариант C).

Runtime-контроль
----------------
:func:`run_notebook` проверяет capability через process-wide
:class:`~src.backend.core.security.capabilities.gate.CapabilityGate` **до**
обращения к Hub — fail-closed: без объявления capability вызов отклоняется
(:class:`CapabilityDeniedError`).
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

from src.backend.core.api import BasePlugin
from src.backend.core.di.providers.jupyter import get_hub_run_provider
from src.backend.core.logging import get_logger
from src.backend.core.security.capabilities.gate import get_capability_gate

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import (
        ActionRegistryProtocol,
        PluginContext,
        ProcessorRegistryProtocol,
        RepositoryRegistryProtocol,
    )

__all__ = (
    "CAPABILITY_NAME",
    "CAPABILITY_SCOPE",
    "JupyterHubPlugin",
    "PLUGIN_NAME",
    "run_notebook",
)

logger = get_logger("extensions.jupyter_hub")

PLUGIN_NAME: str = "jupyter_hub"
"""Имя плагина = namespace его capability-декларации в гейте."""

CAPABILITY_NAME: str = "jupyter.hub"
"""Имя capability (двухсегментное ``<resource>.<verb>``)."""

CAPABILITY_SCOPE: str = "run"
"""Scope capability — verb запуска ноутбука (тот же, что запрашивает роут)."""


async def run_notebook(
    payload: dict[str, Any] | None = None, **_: Any
) -> dict[str, Any]:
    """Запустить notebook на Jupyter Hub под capability-гейтом.

    Единственная разрешённая точка входа к привилегированной операции
    ``jupyter.hub:run``. Вызывается из DSL-шага ``call_function``
    (``ref: extensions.jupyter_hub.plugin:run_notebook``) и из action
    ``jupyter.hub.run`` (REST / GraphQL / SOAP / MCP / WS).

    Args:
        payload: Тело запроса (dict). Поддерживаемые ключи:
            ``notebook_name`` (slug из реестра ноутбуков), ``parameters``
            (dict параметров), ``user_name`` (пользователь JupyterHub),
            ``notebook_path`` (прямой путь к ``.ipynb`` на Hub),
            ``notebook_content_b64`` (inline-notebook в base64) и
            ``output_path``.
        **_: Прочие поля игнорируются (DSL ``call_function`` передаёт
            payload одним позиционным аргументом).

    Returns:
        Результат запуска (поля :class:`HubRunResult`) в виде dict.

    Raises:
        CapabilityDeniedError: capability ``jupyter.hub`` не объявлена
            для этого плагина — вызов отклонён (fail-closed).

    """
    data = dict(payload or {})

    # Fail-closed: без декларации capability операция не выполняется.
    get_capability_gate().check(PLUGIN_NAME, CAPABILITY_NAME, CAPABILITY_SCOPE)

    content: bytes | None = None
    raw_content = data.get("notebook_content_b64")
    if isinstance(raw_content, str) and raw_content:
        try:
            content = base64.b64decode(raw_content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(
                f"notebook_content_b64 is not valid base64: {exc}"
            ) from exc

    result = await get_hub_run_provider()(
        notebook_name=str(data.get("notebook_name") or ""),
        parameters=data.get("parameters") or {},
        user_name=str(data.get("user_name") or "default"),
        notebook_content=content,
        notebook_path_override=data.get("notebook_path"),
        output_path=data.get("output_path"),
    )
    logger.info(
        "jupyter.hub run: notebook=%s user=%s",
        data.get("notebook_name"),
        data.get("user_name") or "default",
    )
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    return dict(result)


class JupyterHubPlugin(BasePlugin):
    """Плагин-провайдер capability ``jupyter.hub``.

    Lifecycle:
    * ``on_load`` — лог загрузки провайдера;
    * ``on_register_actions`` — регистрация action ``jupyter.hub.run``.
    """

    name: str = PLUGIN_NAME
    version: str = "0.1.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Lifecycle hook: вызывается при загрузке плагина."""
        logger.info(
            "jupyter_hub provider loaded (capability %s:%s)",
            CAPABILITY_NAME,
            CAPABILITY_SCOPE,
        )

    async def on_register_actions(self, registry: ActionRegistryProtocol) -> None:
        """Регистрирует action ``jupyter.hub.run`` → :func:`run_notebook`."""
        registry.register("jupyter.hub.run", run_notebook)
        logger.info("jupyter_hub: 1 action registered (jupyter.hub.run)")

    async def on_register_repositories(
        self, registry: RepositoryRegistryProtocol
    ) -> None:
        """Плагин не использует repositories — no-op."""
        return None

    async def on_register_processors(self, registry: ProcessorRegistryProtocol) -> None:
        """Плагин не регистрирует DSL processors — no-op."""
        return None

    async def on_shutdown(self) -> None:
        """Lifecycle hook: cleanup при выгрузке плагина."""
        logger.info("jupyter_hub provider shutdown")
