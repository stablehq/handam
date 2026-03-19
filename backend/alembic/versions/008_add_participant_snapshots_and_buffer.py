"""Add participant_snapshots table and participant_buffer to template_schedules

Revision ID: 008
Revises: 007
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create participant_snapshots table
    op.create_table(
        'participant_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(20), nullable=False),
        sa.Column('male_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('female_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', name='uq_participant_snapshot_date'),
    )
    op.create_index('ix_participant_snapshots_id', 'participant_snapshots', ['id'], unique=False)
    op.create_index('ix_participant_snapshots_date', 'participant_snapshots', ['date'], unique=True)

    # 2. Add participant_buffer to template_schedules
    op.add_column('template_schedules', sa.Column('participant_buffer', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('template_schedules', 'participant_buffer')
    op.drop_index('ix_participant_snapshots_date', table_name='participant_snapshots')
    op.drop_index('ix_participant_snapshots_id', table_name='participant_snapshots')
    op.drop_table('participant_snapshots')
