"""empty message

Revision ID: 96f2014cc24e
Revises: 
Create Date: 2024-11-20 13:00:52.397696

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "96f2014cc24e"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "files",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "object_uuid",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
    )
    op.add_column("orders", sa.Column("file_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_orders_file_id_files"), "orders", "files", ["file_id"], ["id"]
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(op.f("fk_orders_file_id_files"), "orders", type_="foreignkey")
    op.drop_column("orders", "file_id")
    op.drop_table("files")
    # ### end Alembic commands ###
