"""Add manually_extended_until to reservations

Revision ID: 018
Revises: add_stay_group_excluded
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '018'
down_revision: Union[str, None] = 'add_stay_group_excluded'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reservations',
        sa.Column('manually_extended_until', sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('reservations', 'manually_extended_until')
