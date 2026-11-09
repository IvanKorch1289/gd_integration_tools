"""Ключ идемпотентности шага workflow (ADR-0431).

Ключ детерминирован от ``(instance_id, step_name, attempt)`` — одинаковые
входы дают одинаковый ключ, поэтому повторное исполнение того же шага той
же попытки распознаётся в event log'е (ADR-0394) **и** может быть передан
во внешний вызов (заголовок ``Idempotency-Key``), чтобы получатель отбросил
дубликат.

Модуль вынесен отдельно, чтобы runner и executor использовали одну функцию
(иначе circular import: runner → executor → runner).
"""

from __future__ import annotations

import hashlib
from uuid import UUID

__all__ = ("idempotency_key",)


def idempotency_key(instance_id: UUID, step_name: str, attempt: int) -> str:
    """Ключ идемпотентности шага.

    Args:
        instance_id: UUID инстанса workflow'а.
        step_name: Имя шага.
        attempt: Номер попытки.

    Returns:
        hex-хеш ``sha256(instance_id|step_name|attempt)``.

    """
    raw = f"{instance_id}|{step_name}|{attempt}".encode()
    return hashlib.sha256(raw).hexdigest()
