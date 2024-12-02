"""empty message

Revision ID: 4ce1519c5f86
Revises: 2b0a1c946d5f
Create Date: 2024-11-22 12:48:04.823715

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4ce1519c5f86"
down_revision: Union[str, None] = "2b0a1c946d5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "orderfiles",
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_orderfiles_file_id_files")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_orderfiles_order_id_orders")
        ),
        sa.PrimaryKeyConstraint(
            "order_id", "file_id", "id", name=op.f("pk_orderfiles")
        ),
        comment="Связь заказов и файлов",
    )
    op.drop_table("orderfiless")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "orderfiless",
        sa.Column("order_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("file_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(), autoincrement=False, nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name="fk_orderfiless_file_id_files"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_orderfiless_order_id_orders"
        ),
        sa.PrimaryKeyConstraint("order_id", "file_id", "id", name="pk_orderfiless"),
        comment="Связь заказов и файлов",
    )
    op.drop_table("orderfiles")
    # ### end Alembic commands ###
