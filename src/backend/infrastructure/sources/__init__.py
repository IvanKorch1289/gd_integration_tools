"""W23 — Конкретные backends Source + фабрика.

Каждый backend живёт в собственном модуле
(``webhook.py``, ``mq.py``, ``cdc.py``, ...) и собирается через
:func:`build_source` (match по ``SourceKind``).

Тяжёлые зависимости (psycopg3 для CDC, spyne для SOAP, nats-py для NATS)
лениво подгружаются внутри конкретного класса, чтобы dev_light без них
оставался работоспособным.
"""

from src.infrastructure.sources.factory import build_source

__all__ = ("build_source",)
