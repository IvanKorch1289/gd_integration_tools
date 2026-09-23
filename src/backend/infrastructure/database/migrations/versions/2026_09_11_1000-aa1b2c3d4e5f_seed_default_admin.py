"""seed_reference_data — reference data (orderkinds), идемпотентно.

P0 (2026-09-14): привилегированные учётные данные (admin) УДАЛЕНЫ из
миграции — bootstrap администратора теперь явная команда
``manage.py bootstrap-admin`` (пароль через stdin/env; известные дефолты
запрещены в prod-профиле). Миграция создаёт только reference data.

Идемпотентность: повторный ``alembic upgrade head`` безопасен.
Downgrade удаляет только reference-данные.
"""

from typing import Sequence, Union

from alembic import op

from src.backend.infrastructure.database.migrations.seed_data import (  # noqa: F401 — re-export
    apply_reference_seed,
    remove_reference_seed,
)

# revision identifiers, used by Alembic.
revision: str = "aa1b2c3d4e5f"
down_revision: Union[str, None] = "z9a8b7c6d5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert reference data (orderkinds) — идемпотентно."""
    apply_reference_seed(op.get_bind())


def downgrade() -> None:
    """Remove reference data (НЕ удаляет схему)."""
    remove_reference_seed(op.get_bind())
