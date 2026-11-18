"""operators are tagged to a customer

Revision ID: c7a1d4e2b9f3
Revises: b94e5aedaad5
Create Date: 2026-10-30 15:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7a1d4e2b9f3'
down_revision: Union[str, Sequence[str], None] = 'b94e5aedaad5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('customer_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_users_customer_id'), 'users', ['customer_id'], unique=False)
    op.create_foreign_key('fk_users_customer_id', 'users', 'customers', ['customer_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_users_customer_id', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_customer_id'), table_name='users')
    op.drop_column('users', 'customer_id')
