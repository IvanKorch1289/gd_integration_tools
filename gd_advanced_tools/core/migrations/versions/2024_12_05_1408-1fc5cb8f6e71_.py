"""empty message

Revision ID: 1fc5cb8f6e71
Revises: 
Create Date: 2024-12-05 14:08:05.914899

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1fc5cb8f6e71"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "users", "hashed_password", existing_type=sa.VARCHAR(), nullable=False
    )
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.create_unique_constraint(op.f("uq_users_email"), "users", ["email"])
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(op.f("uq_users_email"), "users", type_="unique")
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.alter_column(
        "users", "hashed_password", existing_type=sa.VARCHAR(), nullable=True
    )
    # ### end Alembic commands ###
