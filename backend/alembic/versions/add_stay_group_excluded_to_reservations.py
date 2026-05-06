"""Add stay_group_excluded to reservations

Revision ID: add_stay_group_excluded
Revises: add_lms_title
Create Date: 2026-05-06 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = 'add_stay_group_excluded'
down_revision: Union[str, None] = 'add_lms_title'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reservations',
        sa.Column('stay_group_excluded', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('reservations', 'stay_group_excluded')
