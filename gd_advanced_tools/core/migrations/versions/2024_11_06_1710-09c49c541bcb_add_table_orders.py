"""Add table Orders

Revision ID: 09c49c541bcb
Revises: a001648529bb
Create Date: 2024-11-06 17:10:43.938885

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '09c49c541bcb'
down_revision: Union[str, None] = 'a001648529bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('orders',
    sa.Column('order_kind_id', sa.Integer(), nullable=False),
    sa.Column('pledge_gd_id', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['order_kind_id'], ['orderkinds.id'], name=op.f('fk_orders_order_kind_id_orderkinds')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders'))
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('orders')
    # ### end Alembic commands ###
