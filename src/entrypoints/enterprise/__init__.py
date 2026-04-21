"""Enterprise коннекторы (I1): AS2, EDI X12, SAP IDoc, IBM MQ, JMS, NATS, SFTP.

Все реализации — opt-in через extras `gdi[enterprise]` с специфичными
пакетами. Сам код коннекторов — scaffold-уровень, расширяется по мере
появления проектов.
"""

from __future__ import annotations

__all__ = ("is_enterprise_available",)


def is_enterprise_available() -> bool:
    try:
        import pysftp  # noqa: F401

        return True
    except ImportError:
        return False
