"""Control-flow миксин для RouteBuilder.

Группа: choice / do_try / retry / parallel / saga / fallback / idempotent /
dead_letter / timeout / loop / throttle / delay / circuit_breaker / switch /
expire / correlation_id.

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations


class ControlFlowMixin:
    """Поведенческий миксин control-flow для ``RouteBuilder``.

    Только методы. Без ``@dataclass``, без ``__slots__``, без
    instance-атрибутов. Всё состояние живёт в ``RouteBuilder``;
    миксин обращается к нему через ``self._processors`` и ``self._add()``.
    """

    __slots__ = ()  # type: ignore[var-annotated]
