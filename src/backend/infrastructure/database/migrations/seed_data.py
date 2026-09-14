"""Reference-data seed (идемпотентный): базовые orderkinds.

Привилегированные учётные данные (admin-пользователь) сюда НЕ входят:
bootstrap администратора — явная операция ``manage.py bootstrap-admin``
(пароль только через stdin/env; в prod-профиле слабые/известные пароли
запрещены). Разделение reference data vs privileged credentials —
P0 внешнего плана (2026-09-14).

Используется из двух мест:
- миграция ``aa1b2c3d4e5f`` (PostgreSQL path, ``alembic upgrade head``);
- sqlite-ветка ``env.py`` (W21.2: на sqlite versions/*.py не выполняются,
  таблицы создаются через ``metadata.create_all``).

Идемпотентность: ``ON CONFLICT DO NOTHING`` по уникальному ключу
(orderkinds.skb_uuid). Портативность: даты передаются bind-параметрами
(без ``NOW()`` — на sqlite его нет).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

__all__ = ("apply_reference_seed", "remove_reference_seed")

_DEFAULT_ORDER_KINDS: list[dict[str, Any]] = [
    {
        "name": "registration",
        "description": "Регистрация недвижимости",
        "skb_uuid": "00000000-0000-0000-0000-000000000001",
    },
    {
        "name": "cadastral_passport",
        "description": "Кадастровый паспорт",
        "skb_uuid": "00000000-0000-0000-0000-000000000002",
    },
    {
        "name": "encumbrance_registration",
        "description": "Регистрация обременения",
        "skb_uuid": "00000000-0000-0000-0000-000000000003",
    },
    {
        "name": "ownership_transfer",
        "description": "Переход права собственности",
        "skb_uuid": "00000000-0000-0000-0000-000000000004",
    },
]


def apply_reference_seed(bind: sa.Connection) -> None:
    """Вставить базовые orderkinds (идемпотентно, PG и sqlite)."""
    now = datetime.now(UTC)
    for kind in _DEFAULT_ORDER_KINDS:
        bind.execute(
            sa.text(
                """
                INSERT INTO orderkinds (
                    name, description, skb_uuid, tenant_id, created_at, updated_at
                )
                VALUES (
                    :name, :description, :skb_uuid, :tenant_id, :created_at, :updated_at
                )
                ON CONFLICT (skb_uuid) DO NOTHING
                """
            ),
            {**kind, "tenant_id": "default", "created_at": now, "updated_at": now},
        )


def remove_reference_seed(bind: sa.Connection) -> None:
    """Downgrade: удалить только reference-данные (не схему)."""
    for kind in _DEFAULT_ORDER_KINDS:
        bind.execute(
            sa.text("DELETE FROM orderkinds WHERE skb_uuid = :skb_uuid"),
            {"skb_uuid": kind["skb_uuid"]},
        )
