"""Add manually_edited_fields JSON to reservations (운영자 수정 방명록)

Revision ID: 021
Revises: 020
Create Date: 2026-05-15

운영자가 수정한 필드명과 시각을 dict 로 저장.
naver_sync 가 다음 동기화 시 이 dict 를 보고 덮어쓰기 차단.

예: {"phone": "2026-05-15T10:30:00Z", "customer_name": "2026-05-15T11:00:00Z"}

기존 check_in_pinned / check_out_pinned 컬럼은 PR2 에서 이 컬럼으로 이주 예정.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '021'
down_revision: Union[str, None] = '020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JSON 컬럼 — Postgres 는 JSONB 우선, SQLite 는 JSON (TEXT 로 fallback).
    # SQLAlchemy 의 JSON 타입은 dialect 자동 매핑.
    op.add_column(
        'reservations',
        sa.Column(
            'manually_edited_fields',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column('reservations', 'manually_edited_fields')
