"""trip live location (last known driver position)

Revision ID: d4e8f1a7c2b6
Revises: c7a1d4e2b9f3
Create Date: 2026-11-11 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e8f1a7c2b6'
down_revision: Union[str, Sequence[str], None] = 'c7a1d4e2b9f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trips', sa.Column('last_latitude', sa.Float(), nullable=True))
    op.add_column('trips', sa.Column('last_longitude', sa.Float(), nullable=True))
    op.add_column('trips', sa.Column('last_location_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('trips', 'last_location_at')
    op.drop_column('trips', 'last_longitude')
    op.drop_column('trips', 'last_latitude')
