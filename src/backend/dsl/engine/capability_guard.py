"""Engine-wide enforcement capability в DSL-движке (ADR-0456).

Зачем
-----
До сих пор capability-гейт вызывался **самим процессором** (opt-in):
``BaseProcessor.auth_check()`` внутри ``process()`` — так сделаны БД-,
RPA- и audit-процессоры. Общего пути исполнения шага не было: шаг с
capability-декларацией другого процессора выполнялся **без проверки**,
декларация оставалась декоративной (ADR-0449, открытая позиция №1).

Модуль добавляет единую точку enforcement'а: :func:`enforce_step_capability`
вызывается движком **до** ``processor.process(...)``.

Семантика
---------
* capability берётся из того же источника, что и рантайм
  (:meth:`BaseProcessor._declared_capabilities` — ADR-0449/ADR-0454);
* **шаг без capability-декларации** → enforcement не применяется
  (обратная совместимость: обычные вызовы процессоров вне
  capability-контекста не падают);
* **шаг с декларацией** → проверяется каноническим гейтом
  (:meth:`BaseProcessor.auth_check` → runtime-resolver, ADR-0366):
  namespace = ``route_id`` шага, scope = ``_capability_scope(exchange)``
  (``audit:<action>``-стиля — точки заменены на двоеточия);
* отказ → ``exchange`` переводится в ``failed`` + ``stopped``,
  шаг **не выполняется**, пишется warning-лог.

Идемпотентность
---------------
Проверка не дублируется: :meth:`BaseProcessor.auth_check` помечает
проверенный шаг (атрибут ``capability_verified``), поэтому внутренний
вызов процессора (когда он сам вызывает ``auth_check``) не проверяет
capability второй раз и не плодит audit-события.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange
    from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("enforce_step_capability",)

_logger = get_logger(__name__)


async def enforce_step_capability(
    processor: BaseProcessor, exchange: Exchange[Any], context: ExecutionContext
) -> bool:
    """Проверяет capability шага **до** вызова ``processor.process()``.

    Args:
        processor: Шаг pipeline (экземпляр :class:`BaseProcessor`).
        exchange: Текущий Exchange (источник ``route_id``/tenant/principal).
        context: Контекст исполнения DSL-маршрута.

    Returns:
        ``True`` — шаг может выполняться; ``False`` — отказ capability-гейта
        (exchange уже переведён в ``failed`` + ``stopped``, шаг выполнять
        нельзя).

    """
    capabilities = processor._declared_capabilities()
    if not capabilities:
        # Шаг не объявляет capability → enforcement не применяется.
        return True

    # Маркер проверки сбрасывается перед каждым шагом: иначе повторное
    # использование того же экземпляра процессора в pipeline пропустило бы
    # проверку (маркер ставится в ``auth_check``).
    processor.capability_verified = False

    action = getattr(processor, "capability_action", "execute")
    allowed = await processor.auth_check(exchange, action=action)
    if not allowed:
        _logger.warning(
            "dsl_capability_denied: processor=%s capabilities=%s route=%s error=%s",
            processor.name,
            ",".join(capabilities),
            getattr(exchange.meta, "route_id", None),
            getattr(exchange, "error", None),
        )
    return allowed
