"""employee single address

An employee now has one address (home). It is the pickup point on Pickup trips and the drop point on Drop
trips, so the separate pickup/drop columns go. Existing pickup values are kept as the address.

Revision ID: 46d50334ae2c
Revises: 5d9b1ca9be86
"""
from typing import Sequence, Union

from alembic import op

revision: str = '46d50334ae2c'
down_revision: Union[str, Sequence[str], None] = '5d9b1ca9be86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('employees', 'pickup_address', new_column_name='address')
    op.alter_column('employees', 'pickup_latitude', new_column_name='latitude')
    op.alter_column('employees', 'pickup_longitude', new_column_name='longitude')
    # where only a drop address had been entered, keep it rather than lose it
    op.execute("UPDATE employees SET address = drop_address WHERE address IS NULL")
    for c in ('drop_address', 'drop_latitude', 'drop_longitude'):
        op.drop_column('employees', c)

    op.alter_column('trip_passengers', 'pickup_address', new_column_name='address')
    op.execute("UPDATE trip_passengers SET address = drop_address WHERE address IS NULL")
    op.drop_column('trip_passengers', 'drop_address')


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column('trip_passengers', sa.Column('drop_address', sa.Text(), nullable=True))
    op.execute("UPDATE trip_passengers SET drop_address = address")
    op.alter_column('trip_passengers', 'address', new_column_name='pickup_address')

    op.add_column('employees', sa.Column('drop_address', sa.Text(), nullable=True))
    op.add_column('employees', sa.Column('drop_latitude', sa.Float(), nullable=True))
    op.add_column('employees', sa.Column('drop_longitude', sa.Float(), nullable=True))
    op.execute("UPDATE employees SET drop_address = address")
    op.alter_column('employees', 'longitude', new_column_name='pickup_longitude')
    op.alter_column('employees', 'latitude', new_column_name='pickup_latitude')
    op.alter_column('employees', 'address', new_column_name='pickup_address')
