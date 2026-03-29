"""Add unstable party fields to tenants and reservation_daily_info

- tenants: unstable_business_id, unstable_cookie (언스테이블 네이버 연동)
- reservation_daily_info: unstable_party (날짜별 언스테이블 파티 참여 플래그)

Revision ID: 016
Revises: 015
"""
from alembic import op
import sqlalchemy as sa

revision: str = '016'
down_revision: str = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tenant: 언스테이블 네이버 연동 정보
    op.add_column('tenants', sa.Column('unstable_business_id', sa.String(50), nullable=True))
    op.add_column('tenants', sa.Column('unstable_cookie', sa.Text(), nullable=True))

    # ReservationDailyInfo: 날짜별 언스테이블 파티 참여 플래그
    op.add_column('reservation_daily_info', sa.Column('unstable_party', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('reservation_daily_info', 'unstable_party')
    op.drop_column('tenants', 'unstable_cookie')
    op.drop_column('tenants', 'unstable_business_id')
