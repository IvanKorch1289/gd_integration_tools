"""seed_default_admin — initial data seed (Wave OP-1 / ADR-0296 close M6-#3).

Initial seed migration для bootstrap пустого окружения:

- **admin** user (``is_active=True``, ``is_superuser=True``) с default password
  ``admin-default-password-change-me`` (хэш pbkdf2_sha512 — НЕ plaintext).
  Должен быть сменён при первом login через ``admin_users.change_password``.

- **orderkinds** — базовые виды запросов (default_values для dev/staging/prod):
  - ``registration`` — регистрация недвижимости
  - ``cadastral_passport`` — кадастровый паспорт
  - ``encumbrance_registration`` — регистрация обременения
  - ``ownership_transfer`` — переход права собственности

  Все seeds с явным ``skb_uuid`` (legacy field для интеграции со СКБ-Техно),
  чтобы dev-окружение могло сразу делать интеграционные вызовы без ручной
  настройки.

- **idempotency** — повторный запуск ``alembic upgrade head`` безопасен:
  ``ON CONFLICT DO NOTHING`` на unique constraints.

- **downgrade** удаляет только seeded данные (не схему).

Ops: ``make migrate`` (alembic upgrade head) запускает миграцию + сид.

References:
- ADR-0295 (auth positive flow blocked без seed admin).
- M6-#3 (positive auth scenario).
- tools/checks/pre_prod_check.py (gate #3 cleanup + dry-run).
"""
# flake8: noqa

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "aa1b2c3d4e5f"
down_revision: Union[str, None] = "z9a8b7c6d5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Default admin password hash (pbkdf2_sha512, plaintext: "admin-default-password-change-me").
# ВНИМАНИЕ: пароль помечен для смены при первом login; НЕ для production use as-is.
_DEFAULT_ADMIN_PASSWORD_HASH = (
    "$pbkdf2-sha512$25000$i1Gqda611ppT6r3XOocQ4g$"
    "wS.x/pn5Q/fV/EREjpLpeJHQ0BvB6eHve/1v4RR0kcpfI.yHWgWIEhFwrwoYPg5ddMcZUgXnU7/nH/IpBSDP5Q"
)


# Default orderkinds (canonical SKB integration).
_DEFAULT_ORDER_KINDS = [
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


def upgrade() -> None:
    """Insert default admin user + orderkinds (idempotent)."""
    bind = op.get_bind()

    # 1. Default admin user.
    # Insert с ON CONFLICT DO NOTHING для идемпотентности.
    op.execute(
        sa.text(
            """
            INSERT INTO users (
                username, email, password, is_active, is_superuser,
                created_at, updated_at
            )
            VALUES (
                :username, :email, :password, :is_active, :is_superuser,
                NOW(), NOW()
            )
            ON CONFLICT (username) DO NOTHING
            """
        ),
        {
            "username": "admin",
            "email": "admin@example.com",
            "password": _DEFAULT_ADMIN_PASSWORD_HASH,
            "is_active": True,
            "is_superuser": True,
        },
    )

    # 2. Default orderkinds.
    for kind in _DEFAULT_ORDER_KINDS:
        op.execute(
            sa.text(
                """
                INSERT INTO orderkinds (
                    name, description, skb_uuid, created_at, updated_at
                )
                VALUES (
                    :name, :description, :skb_uuid, NOW(), NOW()
                )
                ON CONFLICT (skb_uuid) DO NOTHING
                """
            ),
            kind,
        )


def downgrade() -> None:
    """Remove seeded data (НЕ удаляет схему)."""
    bind = op.get_bind()

    # Удаляем seeded orderkinds (по skb_uuid для безопасности).
    for kind in _DEFAULT_ORDER_KINDS:
        op.execute(
            sa.text("DELETE FROM orderkinds WHERE skb_uuid = :skb_uuid"),
            {"skb_uuid": kind["skb_uuid"]},
        )

    # Удаляем seeded admin.
    op.execute(
        sa.text("DELETE FROM users WHERE username = :username"),
        {"username": "admin"},
    )
