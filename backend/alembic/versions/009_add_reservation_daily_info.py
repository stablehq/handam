"""Add reservation_daily_info table for per-date party_type

Revision ID: 009
Revises: 008
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reservation_daily_info',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reservation_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(20), nullable=False),
        sa.Column('party_type', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reservation_id', 'date', name='uq_reservation_daily_info'),
    )
    op.create_index('ix_reservation_daily_info_id', 'reservation_daily_info', ['id'], unique=False)
    op.create_index('ix_reservation_daily_date', 'reservation_daily_info', ['reservation_id', 'date'], unique=False)

    # Backfill: for each reservation with party_type set, insert a row for check_in_date
    op.execute("""
        INSERT INTO reservation_daily_info (reservation_id, date, party_type, created_at, updated_at)
        SELECT r.id, r.date, r.party_type, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM reservations r
        WHERE r.party_type IS NOT NULL AND r.party_type != ''
    """)


def downgrade() -> None:
    op.drop_index('ix_reservation_daily_date', table_name='reservation_daily_info')
    op.drop_index('ix_reservation_daily_info_id', table_name='reservation_daily_info')
    op.drop_table('reservation_daily_info')
