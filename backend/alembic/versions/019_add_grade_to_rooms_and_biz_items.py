"""Add grade column to rooms and naver_biz_items

Revision ID: 019
Revises: 018
Create Date: 2026-05-13

Two new nullable Integer columns to support `room_upgrade_review` custom chip:
  - Room.grade           1~5 (도미 < 더블 < 트윈 < 트윈3인실 < 스위트)
  - NaverBizItem.grade   1~5 (예약 상품 등급 — 운영자 지정)

Both nullable. Backfill 없이 시작 — 운영자가 등급 설정 모달에서 직접 입력.
NULL fallback: 비교 불가 → 객후 칩 생성 skip (스케줄 활성 시 critical diag).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '019'
down_revision: Union[str, None] = '018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('rooms', sa.Column('grade', sa.Integer(), nullable=True))
    op.add_column('naver_biz_items', sa.Column('grade', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('naver_biz_items', 'grade')
    op.drop_column('rooms', 'grade')
