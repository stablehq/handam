"""Add check_in_pinned, check_out_pinned to reservations

Revision ID: 020
Revises: 019
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '020'
down_revision: Union[str, None] = '019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reservations',
        sa.Column('check_in_pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'reservations',
        sa.Column('check_out_pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('reservations', 'check_out_pinned')
    op.drop_column('reservations', 'check_in_pinned')
