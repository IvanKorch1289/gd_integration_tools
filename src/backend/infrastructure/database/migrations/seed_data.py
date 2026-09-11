"""Идемпотентный initial-data seed: admin-пользователь + базовые orderkinds.

Используется из двух мест:
- миграция ``aa1b2c3d4e5f`` (PostgreSQL path, ``alembic upgrade head``);
- sqlite-ветка ``env.py`` (W21.2: на sqlite versions/*.py не выполняются,
  таблицы создаются через ``metadata.create_all`` — поэтому seed применяется
  отдельным вызовом :func:`apply_default_seed`).

Идемпотентность: ``ON CONFLICT DO NOTHING`` по уникальным ключам
(users.username, orderkinds.skb_uuid). Портативность: даты передаются
bind-параметрами (без ``NOW()`` — на sqlite его нет).

Безопасность: пароль дефолтного admin — ``admin-default-password-change-me``,
хранится argon2id-хэшем (контракт ``User.verify_password``) и подлежит смене
при первом входе; НЕ для production as-is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

__all__ = ("apply_default_seed", "remove_default_seed")

_DEFAULT_ADMIN_USERNAME = "admin"
# Это argon2id-ХЭШ (не секрет); S105 здесь триггерится на строковый литерал.
_DEFAULT_ADMIN_PASSWORD_HASH = (  # noqa: S105
    "$argon2id$v=19$m=65536,t=3,p=4$v70cgsB+t3Ezpn1nvqvSig$"
    "oBpjlXKJeqdqbyzPTJeAKGtCQSZIF1Ed3U6v5jWOyOA"
)

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


def apply_default_seed(bind: sa.Connection) -> None:
    """Вставить default admin + orderkinds (идемпотентно, PG и sqlite)."""
    now = datetime.now(UTC)
    bind.execute(
        sa.text(
            """
            INSERT INTO users (
                username, email, password, is_active, is_superuser, tenant_id,
                created_at, updated_at
            )
            VALUES (
                :username, :email, :password, :is_active, :is_superuser,
                :tenant_id, :created_at, :updated_at
            )
            ON CONFLICT (username) DO NOTHING
            """
        ),
        {
            "username": _DEFAULT_ADMIN_USERNAME,
            "email": "admin@example.com",
            "password": _DEFAULT_ADMIN_PASSWORD_HASH,
            "is_active": True,
            "is_superuser": True,
            "tenant_id": "default",
            "created_at": now,
            "updated_at": now,
        },
    )
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


def remove_default_seed(bind: sa.Connection) -> None:
    """Downgrade: удалить только seeded данные (не схему)."""
    for kind in _DEFAULT_ORDER_KINDS:
        bind.execute(
            sa.text("DELETE FROM orderkinds WHERE skb_uuid = :skb_uuid"),
            {"skb_uuid": kind["skb_uuid"]},
        )
    bind.execute(
        sa.text("DELETE FROM users WHERE username = :username"),
        {"username": _DEFAULT_ADMIN_USERNAME},
    )
