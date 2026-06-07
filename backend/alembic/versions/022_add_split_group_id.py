"""Add split_group_id to reservations (naver multi-room split linking)

primary↔sibling 영속 연결 키 ("nsplit-{naver_booking_id}").
split-group P1 — 연결 전용 컬럼, sibling 식별은 계속 booking_source='naver_split'.
docs/plans/split-group-step-01-column-and-record.md 참조.

Revision ID: 022
Revises: 021
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = '022'
down_revision: Union[str, None] = '021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reservations',
        sa.Column('split_group_id', sa.String(64), nullable=True),
    )
    op.create_index('ix_reservations_split_group_id', 'reservations', ['split_group_id'])


def downgrade() -> None:
    op.drop_index('ix_reservations_split_group_id', table_name='reservations')
    op.drop_column('reservations', 'split_group_id')
