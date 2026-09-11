"""seed_default_admin — initial data seed (Wave OP-1 / ADR-0296 close M6-#3).

Логика seed'а живёт в :mod:`seed_data` (переиспользуется sqlite-веткой
``env.py``, где versions/*.py не выполняются — см. W21.2).

Идемпотентность: повторный ``alembic upgrade head`` безопасен
(``ON CONFLICT DO NOTHING``). Downgrade удаляет только seeded данные.

Пароль дефолтного admin хранится argon2id-хэшем (контракт
``User.verify_password``); подлежит смене при первом входе.
"""

from typing import Sequence, Union

from alembic import op

from src.backend.infrastructure.database.migrations.seed_data import (
    apply_default_seed,
    remove_default_seed,
)

# revision identifiers, used by Alembic.
revision: str = "aa1b2c3d4e5f"
down_revision: Union[str, None] = "z9a8b7c6d5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert default admin user + orderkinds (идемпотентно)."""
    apply_default_seed(op.get_bind())


def downgrade() -> None:
    """Remove seeded data (НЕ удаляет схему)."""
    remove_default_seed(op.get_bind())
