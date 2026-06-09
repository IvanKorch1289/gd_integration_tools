"""EIPMixinBase — общие импорты и базовый контракт для всех EIP-миксинов.

Sprint 60 W4 — split god-file eip.py (1354 LOC) на 8 per-domain модулей:
  core / routing / sources / transformation / protocols / streaming / messaging / messengers
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

__all__ = ("EIPMixinBase",)


class EIPMixinBase:
    """Базовый класс для всех EIP-миксинов. Не предназначен для прямого использования.

    Контракт (наследуется от RouteBuilder через MRO):
    - ``self._add(processor)`` / ``self._add_lazy(module, name, **kw)`` — добавить processor в pipeline
    - ``self._processors`` — list уже добавленных processors
    - ``self.route_id`` — id текущего route
    - ``self._protocol`` / ``self._transport_config`` — transport binding

    Все методы возвращают ``self`` (или ``self: RouteBuilder``) для fluent chaining.
    """

    __slots__ = ("_protocol", "_transport_config")
